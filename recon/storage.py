import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from recon.cdx_client import Snapshot
from recon.config import ReconConfig

logger = logging.getLogger(__name__)

# Characters unsafe across common filesystems; replaced with "_".
_UNSAFE_CHARS = '<>:"|?*\\'


@dataclass(frozen=True)
class ManifestEntry:
    """One record in _manifest.jsonl — one line per download attempt."""

    url: str
    timestamp: str
    local_path: str  # relative to config.domain_dir
    status: str  # "success" or "failed"
    status_code: str = ""
    mimetype: str = ""
    size: int = 0
    error: str = ""


def _sanitize_segment(segment: str) -> str:
    cleaned = "".join("_" if c in _UNSAFE_CHARS else c for c in segment)
    # Reject traversal segments outright rather than trying to neutralize them.
    if cleaned in ("..", "."):
        return "_"
    return cleaned


def _url_to_path_parts(original: str) -> list[str]:
    """Convert a URL's path component into filesystem-safe path segments."""
    parsed = urlparse(original)
    path = parsed.path or "/"
    if path.endswith("/"):
        path += "index.html"
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        segments = ["index.html"]
    return [_sanitize_segment(seg) for seg in segments]


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def allocate_paths(
    snapshots: list[Snapshot], all_snapshots: bool
) -> dict[tuple[str, str], Path]:
    """Precompute local file paths for every snapshot.

    Returns a mapping of (original_url, timestamp) -> relative Path
    (relative to config.domain_dir). Snapshots are grouped by their path
    parts (plus timestamp bucket, when all_snapshots is on); only groups
    with more than one distinct URL (i.e. a genuine query-string collision
    on the same path) get a hash suffix, keeping the common case readable.
    """
    groups: dict[tuple, list[Snapshot]] = {}
    for snap in snapshots:
        parts = tuple(_url_to_path_parts(snap.original))
        bucket = snap.timestamp if all_snapshots else "latest"
        key = (bucket, parts)
        groups.setdefault(key, []).append(snap)

    result: dict[tuple[str, str], Path] = {}
    for (bucket, parts), group in groups.items():
        distinct_urls = {s.original for s in group}
        needs_hash = len(distinct_urls) > 1
        prefix = Path("latest") if bucket == "latest" else Path("snapshots") / bucket

        for snap in group:
            path_parts = list(parts)
            if needs_hash:
                *dirs, filename = path_parts
                stem, _, ext = filename.rpartition(".")
                suffix = _short_hash(snap.original)
                if ext:
                    filename = f"{stem}__{suffix}.{ext}"
                else:
                    filename = f"{filename}__{suffix}"
                path_parts = [*dirs, filename]
            result[(snap.original, snap.timestamp)] = prefix.joinpath(*path_parts)

    return result


def write_content(config: ReconConfig, relative_path: Path, content: bytes) -> int:
    """Write downloaded bytes to disk under config.domain_dir, return size."""
    full_path = config.domain_dir / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)
    return len(content)


class ManifestStore:
    """Tracks download outcomes for resume support.

    Loads existing entries on init (building a skip-set of already-succeeded
    downloads) and appends new entries as downloads complete, flushing each
    write so a crash mid-run doesn't lose progress. Safe for concurrent use
    from multiple downloader threads.
    """

    def __init__(self, config: ReconConfig):
        self._config = config
        self._lock = threading.Lock()
        self._succeeded: set[tuple[str, str]] = set()
        self._file = None
        self._load_existing()

    def _load_existing(self) -> None:
        self._config.domain_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._config.manifest_path

        if not self._config.fresh and manifest_path.exists():
            with manifest_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        logger.warning("Skipping malformed manifest line")
                        continue
                    if record.get("status") == "success":
                        self._succeeded.add((record["url"], record["timestamp"]))

            logger.info(
                "Resume: %d previously succeeded downloads loaded from manifest",
                len(self._succeeded),
            )

        # "fresh" truncates; resume (default) appends to the existing file.
        mode = "w" if self._config.fresh else "a"
        self._file = manifest_path.open(mode, encoding="utf-8")

    def already_succeeded(self, url: str, timestamp: str) -> bool:
        return (url, timestamp) in self._succeeded

    def record(self, entry: ManifestEntry) -> None:
        """Append one manifest entry, thread-safe, flushed immediately."""
        with self._lock:
            self._file.write(json.dumps(asdict(entry)) + "\n")
            self._file.flush()
            if entry.status == "success":
                self._succeeded.add((entry.url, entry.timestamp))

    def close(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()
