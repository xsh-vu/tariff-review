from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar


ResultT = TypeVar("ResultT")


class AutoScrollingStatus:
    """Write progress updates and smoothly follow the newest status item."""

    def __init__(self, status: Any) -> None:
        self._status = status
        self._instance_id = uuid.uuid4().hex
        self._message_index = 0

    def write(self, message: str) -> None:
        self._status.write(message)
        self._message_index += 1
        marker_id = f"progress-{self._instance_id}-{self._message_index}"
        self._status.html(
            f"""
            <span id="{marker_id}" aria-hidden="true" style="display:block;height:0"></span>
            <script>
            requestAnimationFrame(() => requestAnimationFrame(() => {{
                document.getElementById("{marker_id}")?.scrollIntoView({{
                    behavior: "smooth",
                    block: "nearest"
                }});
            }}));
            </script>
            """,
            unsafe_allow_javascript=True,
        )

    def update(self, **kwargs: Any) -> None:
        self._status.update(**kwargs)


def run_with_heartbeat(
    operation: Callable[[Callable[[str], None]], ResultT],
    emit: Callable[[str], None],
    *,
    waiting_message: str,
    heartbeat_seconds: float = 4.0,
    poll_seconds: float = 0.1,
) -> ResultT:
    """Keep Streamlit's main thread responsive during a blocking API call."""
    updates: queue.Queue[tuple[str, object]] = queue.Queue()

    def report(message: str) -> None:
        updates.put(("message", message))

    def work() -> None:
        try:
            updates.put(("result", operation(report)))
        except BaseException as exc:  # Re-raised unchanged on the UI thread.
            updates.put(("error", exc))

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    last_visible_update = time.perf_counter()
    started = last_visible_update
    result: ResultT | None = None
    error: BaseException | None = None

    while worker.is_alive() or not updates.empty():
        try:
            kind, value = updates.get(timeout=poll_seconds)
        except queue.Empty:
            now = time.perf_counter()
            if now - last_visible_update >= heartbeat_seconds:
                emit(
                    f"Still working · {waiting_message} "
                    f"({now - started:.0f}s elapsed)."
                )
                last_visible_update = now
            continue

        if kind == "message":
            emit(str(value))
            last_visible_update = time.perf_counter()
        elif kind == "result":
            result = value  # type: ignore[assignment]
        elif kind == "error":
            error = value if isinstance(value, BaseException) else RuntimeError(str(value))

    worker.join()
    if error is not None:
        raise error
    return result  # type: ignore[return-value]
