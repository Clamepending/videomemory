"""URL helpers for network streams."""

from urllib.parse import urlparse


def is_snapshot_url(url: str) -> bool:
    """Return True if the URL looks like a single-image HTTP snapshot endpoint."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return False
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    return (
        path.endswith((".jpg", ".jpeg")) or
        "snapshot" in path or
        "snapshot" in query
    )


def get_pull_url(url: str) -> str:
    """Return the URL to use for pulling (OpenCV/FFmpeg)."""
    if not url or not isinstance(url, str):
        return url
    return url.strip()
