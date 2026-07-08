# Aletheia

Recon tool that queries the Internet Archive Wayback Machine for a target
domain and downloads all archived files.

## Status: v1.1 — filtering, random UA, sqlmap-style output

All modules implemented and functionally tested against mocked HTTP
boundaries during development (no pytest suite checked in yet — see notes
below):

- `recon/config.py` — `ReconConfig` dataclass, all runtime tunables, `VERSION`
- `recon/cdx_client.py` — CDX API querying, pagination + retry/backoff,
  optional random User-Agent
- `recon/storage.py` — deterministic collision-safe path allocation,
  manifest-based resume tracking, file writes
- `recon/downloader.py` — concurrent downloads, shared rate limiter,
  retry/backoff, resume-aware skipping, optional random User-Agent
- `recon/url_filter.py` — allowlist filtering by extension and/or MIME
  type, applied before path allocation/download
- `recon/user_agents.py` — static desktop browser UA list + rotation
- `recon/cli.py` — argparse entry point, sqlmap-style bracket-tag log
  format (`[HH:MM:SS] [LEVEL] message`, no coloring) + plain-text banner
- `aletheia.py` — standalone entry point script for running without
  `pip install`; verified to work from any working directory

Full pipeline verified end-to-end (CDX parse → filter → path allocation →
download → manifest write) with the network boundary mocked.

## Install & usage

**Option 1 — pip install (recommended):**

```bash
pip install -e .
aletheia example.com
```

**Option 2 — no install, standalone script:**

```bash
pip install requests   # only dependency needed
python aletheia.py example.com
```

`aletheia.py` at the project root works from any working directory and
calls the exact same code path as the installed `aletheia` command — no
functional difference between the two options, just whether the package
gets installed.

Common flags:

```bash
aletheia example.com --all-snapshots          # every historical snapshot, not just latest
aletheia example.com --concurrency 8          # more parallel download workers
aletheia example.com --rate-limit 3           # requests/sec ceiling to archive.org
aletheia example.com --fresh                  # ignore existing manifest, re-download everything
aletheia example.com --output-dir ~/recon     # custom output root
aletheia example.com --filter-ext js,css      # only download these extensions
aletheia example.com --filter-mime image/     # only download this MIME category
aletheia example.com --random-agent           # rotate UA header per request
aletheia example.com -v                       # debug logging
```

`--filter-ext` and `--filter-mime` are both allowlist-only. If both are
given, a snapshot must match both (extension AND mimetype category); a
snapshot only needs to match one value within a single filter's list.

Output lands in `<output-dir>/<domain>/`:
- `latest/` — mirrors the site's URL structure (default mode)
- `snapshots/<timestamp>/` — used instead when `--all-snapshots` is set
- `_manifest.jsonl` — one record per download attempt; re-running the same
  command automatically resumes and skips prior successes

## Notes / open verification items

- `cdx_client._paginated_query`'s resume-key parsing is implemented per
  archive.org's documented CDX pagination behavior but has not been
  verified against a **live** response (archive.org isn't reachable from
  the sandbox this was built in). Everything else — path allocation,
  manifest/resume, download retry/backoff, rate limiting, filtering,
  random UA, CLI wiring — has been functionally tested, including full
  end-to-end runs with only the network layer mocked. Worth a real run
  against a small/low-traffic domain first to confirm pagination behaves
  as expected before pointing it at a large target.
- No formal test suite (pytest) is set up yet — testing so far was done
  via ad hoc scripts during development, not checked into the repo.
- Banner is a plain title/subtitle/rule, not full ASCII art — flagged in
  case a more elaborate sqlmap-style logo is wanted.
- `recon/` has no `__init__.py` by design — it's a PEP 420 namespace
  package. This required adding a `[build-system]` table to
  `pyproject.toml`, which was actually missing before (an oversight from
  the initial scaffold) — `pip install -e .` would not have worked
  correctly until this fix. Verified with a real editable install in an
  isolated venv: build succeeds, the `aletheia` console-script runs, and
  `recon.cli` imports correctly from the installed package.
