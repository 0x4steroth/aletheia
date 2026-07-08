# Aletheia

Recon tool that queries the Internet Archive Wayback Machine for a target
domain and downloads all archived files.

## Install & usage

**Option 1 — pip install (recommended):**

```bash
pip install -e .
aletheia example.com
```

**Option 2 — no install, standalone script:**

```bash
pip install requests   # only dependency needed
python3 aletheia example.com
```

`aletheia` at the project root works from any working directory and
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
