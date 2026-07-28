"""Hard wall-clock deadline for blocking I/O (urllib can miss mid-stream timeouts)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Callable, TypeVar

T = TypeVar("T")

# Reuse a small pool so we don't spawn unbounded threads under load.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nlu-http")


def run_with_deadline(fn: Callable[[], T], *, seconds: float) -> T:
    """
    Run fn in a worker thread and raise TimeoutError if it exceeds `seconds`.

    Note: the worker may continue briefly after timeout (urllib cannot be hard-killed),
    but the caller unblocks immediately and can fall back.
    """
    future = _executor.submit(fn)
    try:
        return future.result(timeout=max(0.1, float(seconds)))
    except FuturesTimeout as exc:
        future.cancel()
        raise TimeoutError(f"operation exceeded {seconds}s") from exc
