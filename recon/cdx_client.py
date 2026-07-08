"""Client for the Internet Archive CDX Server API.

The CDX API returns the list of known snapshots for a domain — timestamps,
original URLs, status codes, mimetypes — without fetching any actual file
content. Content download is handled later by downloader.py; this module
is listing-only.

NOTE ON PAGINATION (assumption flagged for verification): this implements
the documented `showResumeKey` streaming pagination mode. archive.org's
CDX API is not reachable from this sandbox to test live, so the resume-key
parsing should be verified against a real response on first run — if the
response shape differs, the fix is isolated to `_paginated_query`.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

import requests

from recon.config import CDX_API_BASE, ReconConfig
from recon.user_agents import random_user_agent

logger = logging.getLogger(__name__)

# Fields requested from the CDX API, in order. This order must match the
# positional unpacking in _row_to_snapshot below.
CDX_FIELDS = ["timestamp", "original", "mimetype", "statuscode", "digest", "length"]

# Number of rows requested per page during pagination.
PAGE_LIMIT = 10_000


@dataclass(frozen=True)
class Snapshot:
    """A single archived URL entry as reported by the CDX API."""

    timestamp: str
    original: str
    mimetype: str
    statuscode: str
    digest: str
    length: str


class CdxQueryError(Exception):
    """Raised when the CDX API cannot be queried successfully after retries."""


def fetch_snapshots(config: ReconConfig) -> Iterator[Snapshot]:
    """Yield all snapshots for config.target, honoring config.all_snapshots.

    When all_snapshots is False, uses CDX's collapse=urlkey to return only
    the most recent snapshot per unique URL — cheaper both on the API call
    and on the eventual download volume.
    """
    params = {
        "url": f"{config.target}/*",
        "matchType": "domain",
        "output": "json",
        "fl": ",".join(CDX_FIELDS),
        "filter": "statuscode:200",
    }
    if not config.all_snapshots:
        params["collapse"] = "urlkey"

    yield from _paginated_query(config, params)


def _paginated_query(
    config: ReconConfig, base_params: dict[str, str]
) -> Iterator[Snapshot]:
    params = dict(base_params)
    params["limit"] = str(PAGE_LIMIT)
    params["showResumeKey"] = "true"

    resume_key: str | None = None
    while True:
        if resume_key:
            params["resumeKey"] = resume_key

        rows = _request_with_retry(config, params)
        if not rows:
            return

        # First row is the header when this is the first page fetched fresh;
        # the CDX API only sends it once per response, not once per session,
        # so every response's first row is checked and skipped if it matches.
        data_rows = rows
        if data_rows and data_rows[0] == CDX_FIELDS:
            data_rows = data_rows[1:]

        # Resume key convention: an empty row followed by a single-element
        # row containing the key, appended at the end of the page.
        resume_key = None
        if len(data_rows) >= 2 and data_rows[-2] == []:
            resume_key = data_rows[-1][0]
            data_rows = data_rows[:-2]

        for row in data_rows:
            yield _row_to_snapshot(row)

        if not resume_key:
            return


def _row_to_snapshot(row: list[str]) -> Snapshot:
    timestamp, original, mimetype, statuscode, digest, length = row
    return Snapshot(
        timestamp=timestamp,
        original=original,
        mimetype=mimetype,
        statuscode=statuscode,
        digest=digest,
        length=length,
    )


def _request_with_retry(config: ReconConfig, params: dict[str, str]) -> list[list[str]]:
    """Issue one CDX request, retrying with exponential backoff on failure."""
    last_error: Exception | None = None

    for attempt in range(config.max_retries):
        try:
            headers = {"User-Agent": random_user_agent()} if config.random_agent else {}
            response = requests.get(
                CDX_API_BASE,
                params=params,
                headers=headers,
                timeout=config.timeout_seconds,
            )
            if response.status_code == 429:
                wait = 2**attempt
                logger.warning("CDX rate-limited (429), backing off %ss", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()

            if not response.text.strip():
                return []
            return response.json()

        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            wait = 2**attempt
            logger.warning(
                "CDX request failed (attempt %s/%s): %s — retrying in %ss",
                attempt + 1,
                config.max_retries,
                exc,
                wait,
            )
            time.sleep(wait)

    raise CdxQueryError(
        f"CDX query failed after {config.max_retries} attempts"
    ) from last_error
