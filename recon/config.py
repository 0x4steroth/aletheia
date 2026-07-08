from dataclasses import dataclass
from pathlib import Path

# archive.org's CDX API is unauthenticated but informally rate-limited;
# aggressive polling gets 429s or temporary IP blocks. Keep defaults
# conservative — users can override via CLI flags once cli.py lands.
DEFAULT_CONCURRENCY = 4
DEFAULT_RATE_LIMIT_PER_SEC = 2.0
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 5

CDX_API_BASE = "http://web.archive.org/cdx/search/cdx"
WAYBACK_FETCH_BASE = "https://web.archive.org/web"


@dataclass
class ReconConfig:
    """Holds all settings for a single recon run against one target domain."""

    target: str
    output_dir: Path = Path("output")

    # Snapshot scope: False = latest snapshot per URL only (deduped),
    # True = every historical snapshot (namespaced by timestamp on disk).
    all_snapshots: bool = False

    # Download behavior
    concurrency: int = DEFAULT_CONCURRENCY
    rate_limit_per_sec: float = DEFAULT_RATE_LIMIT_PER_SEC
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES

    # Resume behavior: if a manifest already exists for this target,
    # entries marked "success" are skipped unless fresh=True forces
    # a full re-download.
    fresh: bool = False

    # If True, each request uses a randomly chosen desktop browser
    # User-Agent header instead of the default requests/urllib UA.
    random_agent: bool = False

    @property
    def domain_dir(self) -> Path:
        """Output root for this specific target, e.g. output/<domain>/."""
        return self.output_dir / self.target

    @property
    def manifest_path(self) -> Path:
        return self.domain_dir / "_manifest.jsonl"
