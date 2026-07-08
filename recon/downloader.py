import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests

from recon.cdx_client import Snapshot
from recon.config import WAYBACK_FETCH_BASE, ReconConfig
from recon.storage import ManifestEntry, ManifestStore, allocate_paths, write_content
from recon.user_agents import random_user_agent

logger = logging.getLogger(__name__)


@dataclass
class DownloadSummary:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.downloaded + self.skipped + self.failed


class RateLimiter:
    """Enforces a minimum interval between requests, shared across threads.

    This is deliberately simple (fixed interval, not a token bucket) —
    archive.org's actual limits aren't published, so a conservative fixed
    spacing is easier to reason about and tune than bucket parameters.
    """

    def __init__(self, rate_per_sec: float):
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = threading.Lock()
        self._last_call = 0.0

    def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._last_call + self._min_interval - now
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()


def build_wayback_url(snapshot: Snapshot) -> str:
    # The "id_" modifier returns the original captured bytes unmodified —
    # without it, the Wayback Machine injects a toolbar and rewrites links
    # in HTML/JS/CSS responses, which would corrupt downloaded content.
    return f"{WAYBACK_FETCH_BASE}/{snapshot.timestamp}id_/{snapshot.original}"


def _download_one(
    config: ReconConfig,
    snapshot: Snapshot,
    relative_path: Path,
    manifest: ManifestStore,
    rate_limiter: RateLimiter,
    session: requests.Session,
) -> str:
    """Download a single snapshot. Returns "downloaded", "skipped", or "failed"."""
    if not config.fresh and manifest.already_succeeded(
        snapshot.original, snapshot.timestamp
    ):
        return "skipped"

    url = build_wayback_url(snapshot)
    last_error: Exception | None = None

    for attempt in range(config.max_retries):
        rate_limiter.acquire()
        try:
            headers = {"User-Agent": random_user_agent()} if config.random_agent else {}
            response = session.get(url, headers=headers, timeout=config.timeout_seconds)
            if response.status_code == 429:
                wait = 2**attempt
                logger.warning("Download rate-limited (429), backing off %ss", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()

            size = write_content(config, relative_path, response.content)
            manifest.record(
                ManifestEntry(
                    url=snapshot.original,
                    timestamp=snapshot.timestamp,
                    local_path=str(relative_path),
                    status="success",
                    status_code=str(response.status_code),
                    mimetype=snapshot.mimetype,
                    size=size,
                )
            )
            return "downloaded"

        except (requests.RequestException, OSError) as exc:
            last_error = exc
            wait = 2**attempt
            logger.warning(
                "Download failed for %s (attempt %s/%s): %s",
                snapshot.original,
                attempt + 1,
                config.max_retries,
                exc,
            )
            time.sleep(wait)

    manifest.record(
        ManifestEntry(
            url=snapshot.original,
            timestamp=snapshot.timestamp,
            local_path=str(relative_path),
            status="failed",
            mimetype=snapshot.mimetype,
            error=str(last_error) if last_error else "unknown error",
        )
    )
    return "failed"


def run_downloads(config: ReconConfig, snapshots: list[Snapshot]) -> DownloadSummary:
    """Download all given snapshots, respecting concurrency and rate limits."""
    manifest = ManifestStore(config)
    paths = allocate_paths(snapshots, config.all_snapshots)
    rate_limiter = RateLimiter(config.rate_limit_per_sec)
    session = requests.Session()

    summary = DownloadSummary()
    summary_lock = threading.Lock()

    def task(snap: Snapshot) -> None:
        relative_path = paths[(snap.original, snap.timestamp)]
        result = _download_one(
            config, snap, relative_path, manifest, rate_limiter, session
        )
        with summary_lock:
            setattr(summary, result, getattr(summary, result) + 1)

    executor = ThreadPoolExecutor(max_workers=config.concurrency)
    try:
        futures = [executor.submit(task, snap) for snap in snapshots]

        for future in as_completed(futures):
            future.result()  # Re-raises exceptions from task()

    except KeyboardInterrupt:
        print("\nInterrupted. Stopping workers...")

        executor.shutdown(wait=False, cancel_futures=True)
        raise

    finally:
        manifest.close()
        session.close()

    logger.info(
        "Done: %d downloaded, %d skipped, %d failed",
        summary.downloaded,
        summary.skipped,
        summary.failed,
    )
    return summary
