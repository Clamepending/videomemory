"""Shared asyncio background loop helpers for stream ingestors."""

import asyncio
import logging
import threading
import time
from typing import Optional


logger = logging.getLogger("VideoStreamIngestor")

_flask_background_loop: Optional[asyncio.AbstractEventLoop] = None
_background_loop_thread: Optional[threading.Thread] = None
_background_loop_lock = threading.Lock()


def _run_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run a persistent event loop in a daemon thread."""

    asyncio.set_event_loop(loop)
    loop.run_forever()


def _is_usable_loop(loop: Optional[asyncio.AbstractEventLoop]) -> bool:
    return loop is not None and not loop.is_closed() and loop.is_running()


def get_background_loop(
    preferred_loop: Optional[asyncio.AbstractEventLoop] = None,
) -> Optional[asyncio.AbstractEventLoop]:
    """Return a running background loop, creating a fallback one if needed."""

    global _flask_background_loop, _background_loop_thread

    if _is_usable_loop(preferred_loop):
        _flask_background_loop = preferred_loop
        return preferred_loop

    if _is_usable_loop(_flask_background_loop):
        return _flask_background_loop

    with _background_loop_lock:
        if _is_usable_loop(preferred_loop):
            _flask_background_loop = preferred_loop
            return preferred_loop
        if _is_usable_loop(_flask_background_loop):
            return _flask_background_loop

        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_background_loop,
            args=(loop,),
            daemon=True,
            name="VideoMemoryBackgroundLoop",
        )
        thread.start()

        deadline = time.monotonic() + 0.5
        while not loop.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)

        if not loop.is_running():
            logger.error("Failed to start fallback background event loop")
            try:
                loop.close()
            except Exception:
                pass
            return None

        _flask_background_loop = loop
        _background_loop_thread = thread
        logger.info("Started fallback background event loop for VideoStreamIngestor")
        return loop
