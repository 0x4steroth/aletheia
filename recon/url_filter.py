from urllib.parse import urlparse

from recon.cdx_client import Snapshot


def _get_extension(url: str) -> str:
    path = urlparse(url).path
    last_segment = path.rsplit("/", 1)[-1]
    if "." not in last_segment:
        return ""
    return last_segment.rsplit(".", 1)[-1].lower()


def _mimetype_matches(mimetype: str, allowed: set[str]) -> bool:
    mimetype = mimetype.lower()
    for pattern in allowed:
        # A trailing "/" means a category prefix match, e.g. "image/"
        # matches "image/png", "image/jpeg", etc.
        if pattern.endswith("/"):
            if mimetype.startswith(pattern):
                return True
        elif mimetype == pattern:
            return True
    return False


def filter_snapshots(
    snapshots: list[Snapshot],
    extensions: set[str] | None = None,
    mimetypes: set[str] | None = None,
) -> list[Snapshot]:
    """Return only snapshots matching the given filter criteria.

    extensions: e.g. {"js", "css", "png"} — matched against the URL's
    file extension, case-insensitive, leading dots stripped.
    mimetypes: e.g. {"text/html", "image/"} — exact match, or category
    prefix match if the pattern ends with "/".
    """
    if not extensions and not mimetypes:
        return snapshots

    normalized_exts = (
        {e.lower().lstrip(".") for e in extensions} if extensions else None
    )
    normalized_mimes = {m.lower() for m in mimetypes} if mimetypes else None

    result = []
    for snap in snapshots:
        if (
            normalized_exts is not None
            and _get_extension(snap.original) not in normalized_exts
        ):
            continue
        if normalized_mimes is not None and not _mimetype_matches(
            snap.mimetype, normalized_mimes
        ):
            continue
        result.append(snap)
    return result
