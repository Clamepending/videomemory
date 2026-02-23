"""URL helpers for network streams (e.g. RTMP → RTSP for pull)."""

import os
from urllib.parse import urlparse, urlunparse


def get_pull_url(url: str) -> str:
    """Return the URL to use for pulling (OpenCV/FFmpeg). RTMP is not reliably
    pullable by OpenCV; convert to RTSP so the server can pull from the same
    host. Non-RTMP URLs are returned unchanged.

    Convention (MediaMTX default): rtmp://host[:port]/app/stream
    → rtsp://host:RTSP_PORT/app/stream. RTSP port is from env
    VIDEOMEMORY_RTSP_PULL_PORT (default 8554). For SRS use 1935.
    """
    if not url or not isinstance(url, str):
        return url
    u = url.strip()
    if not u.lower().startswith("rtmp://"):
        return url
    try:
        parsed = urlparse(u)
        host = parsed.hostname or ""
        rtsp_port = os.environ.get("VIDEOMEMORY_RTSP_PULL_PORT", "8554")
        path = parsed.path or "/live/default"
        netloc = f"{host}:{rtsp_port}" if host else ""
        return urlunparse(("rtsp", netloc, path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        return url
