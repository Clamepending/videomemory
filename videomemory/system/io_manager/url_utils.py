"""URL helpers for network streams (e.g. push URL -> RTSP pull URL)."""

import os
from urllib.parse import parse_qs, urlparse, urlunparse


def get_pull_url(url: str) -> str:
    """Return the URL to use for pulling (OpenCV/FFmpeg).

    Converts common *push* ingest URLs (RTMP, SRT, WHIP/WebRTC ingest aliases)
    into an RTSP pull URL for VideoMemory's ingestor when possible.
    """
    if not url or not isinstance(url, str):
        return url
    u = url.strip()
    try:
        parsed = urlparse(u)
        scheme = (parsed.scheme or "").lower()
        host = parsed.hostname or ""
        rtsp_port = os.environ.get("VIDEOMEMORY_RTSP_PULL_PORT", "8554")
        netloc = f"{host}:{rtsp_port}" if host else ""

        if scheme == "rtmp":
            path = parsed.path or "/live/default"
            return urlunparse(("rtsp", netloc, path, parsed.params, parsed.query, parsed.fragment))

        if scheme == "srt":
            # MediaMTX publish URLs often encode the stream path in streamid:
            # srt://host:8890?streamid=publish:live/stream
            qs = parse_qs(parsed.query or "")
            streamid = (qs.get("streamid") or [""])[0]
            if streamid.startswith("publish:"):
                stream_path = "/" + streamid.split("publish:", 1)[1].lstrip("/")
                return urlunparse(("rtsp", netloc, stream_path, "", "", ""))
            # Fallback if someone used a pathful SRT URL variant.
            if parsed.path:
                return urlunparse(("rtsp", netloc, parsed.path, "", "", ""))
            return url

        if scheme == "whip":
            path = parsed.path or "/live/default"
            return urlunparse(("rtsp", netloc, path, "", "", ""))

        # Allow conversion from explicit WHIP HTTP endpoint URLs if they end with /whip.
        if scheme in ("http", "https") and parsed.path.endswith("/whip"):
            base_path = parsed.path[: -len("/whip")] or "/live/default"
            return urlunparse(("rtsp", netloc, base_path, "", "", ""))

        return url
    except Exception:
        return url
