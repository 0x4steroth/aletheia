import argparse
import logging
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

from recon.cdx_client import CdxQueryError, fetch_snapshots
from recon.config import (
    DEFAULT_CONCURRENCY,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RATE_LIMIT_PER_SEC,
    DEFAULT_TIMEOUT_SECONDS,
    ReconConfig,
)
from recon.downloader import run_downloads
from recon.url_filter import filter_snapshots

logger = logging.getLogger("recon.cli")

PROGRAM_NAME = "aletheia"


def print_banner() -> None:
    """Plain-text startup banner, sqlmap-style structure without coloring."""
    print("\nAletheia - Wayback Machine Recon & Archive Downloader")
    print("Author: 0x4steroth")


class BracketTagFormatter(logging.Formatter):
    """Renders log lines as "[HH:MM:SS] [LEVEL] message" (sqlmap-style, no color)."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%H:%M:%S")
        return f"[{timestamp}] [{record.levelname}] {record.getMessage()}"


def normalize_target(raw: str) -> str:
    """Reduce a user-provided target to a bare domain (lowercase, no scheme/path).

    Accepts "example.com", "https://example.com", or "https://example.com/"
    and returns "example.com" in every case.
    """
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    netloc = parsed.netloc or parsed.path
    return netloc.strip("/").lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aletheia",
        description="Download all archived files for a target domain from the Wayback Machine.",
    )
    parser.add_argument("target", help="Target domain, e.g. example.com")
    parser.add_argument(
        "--all-snapshots",
        action="store_true",
        help="Download every historical snapshot instead of only the latest per URL",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Root output directory (default: ./output)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Number of concurrent download workers (default: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=DEFAULT_RATE_LIMIT_PER_SEC,
        dest="rate_limit_per_sec",
        help=f"Max requests/sec to archive.org (default: {DEFAULT_RATE_LIMIT_PER_SEC})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        dest="timeout_seconds",
        help="Per-request timeout in seconds",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        dest="max_retries",
        help="Max retry attempts per request before giving up",
    )
    parser.add_argument(
        "--filter-ext",
        dest="filter_ext",
        default=None,
        help="Comma-separated file extensions to include, e.g. js,css,png",
    )
    parser.add_argument(
        "--filter-mime",
        dest="filter_mime",
        default=None,
        help="Comma-separated MIME types to include, e.g. text/html,image/ "
        "(a trailing slash matches the whole category)",
    )
    parser.add_argument(
        "--random-agent",
        action="store_true",
        help="Rotate a random desktop browser User-Agent header per request",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore any existing manifest and re-download everything",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    return parser


def build_config(args: argparse.Namespace) -> ReconConfig:
    return ReconConfig(
        target=normalize_target(args.target),
        output_dir=args.output_dir,
        all_snapshots=args.all_snapshots,
        concurrency=args.concurrency,
        rate_limit_per_sec=args.rate_limit_per_sec,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        fresh=args.fresh,
        random_agent=args.random_agent,
    )


def parse_filter_set(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def delimiter_timestamp(string):
    """Prints a standardized timestamp delimiter block to the terminal."""
    now = datetime.now()
    print(f"\n[*] {string} @ {now.strftime('%H:%M:%S')} /{now.strftime('%Y-%m-%d')}/\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    print_banner()
    delimiter_timestamp("starting")

    try:
        handler = logging.StreamHandler()
        handler.setFormatter(BracketTagFormatter())
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            handlers=[handler],
        )

        config = build_config(args)
        logger.info("Target: %s", config.target)
        logger.info(
            "Mode: %s, concurrency=%d, rate-limit=%s/s, random-agent=%s",
            "all-snapshots" if config.all_snapshots else "latest-only",
            config.concurrency,
            config.rate_limit_per_sec,
            config.random_agent,
        )

        logger.info("Querying CDX for snapshot list...")
        try:
            snapshots = list(fetch_snapshots(config))
        except CdxQueryError as exc:
            logger.error("Failed to query CDX API: %s", exc)
            return 1

        if not snapshots:
            logger.warning("No snapshots found for %s", config.target)
            return 0

        logger.info("Found %d snapshot(s)", len(snapshots))

        filter_extensions = parse_filter_set(args.filter_ext)
        filter_mimetypes = parse_filter_set(args.filter_mime)
        if filter_extensions or filter_mimetypes:
            before = len(snapshots)
            snapshots = filter_snapshots(
                snapshots, extensions=filter_extensions, mimetypes=filter_mimetypes
            )
            logger.info(
                "Filter applied: %d/%d snapshot(s) matched", len(snapshots), before
            )

        if not snapshots:
            logger.warning("No snapshots left after filtering")
            return 0

        summary = run_downloads(config, snapshots)
        logger.info(
            "Done — downloaded: %d, skipped: %d, failed: %d",
            summary.downloaded,
            summary.skipped,
            summary.failed,
        )

        return 0 if summary.failed == 0 else 1

    except KeyboardInterrupt:
        logger.warning("Interrupted by user, exiting...")
        return 1

    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1

    finally:
        delimiter_timestamp("ending")
