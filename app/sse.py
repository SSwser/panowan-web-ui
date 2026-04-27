"""Server-Sent Events broadcast bus for job status updates."""

import asyncio
import json
import threading
from typing import Any


class SSEBus:
    """Simple pub/sub bus for SSE job events.

    Thread-safe: broadcast() can be called from any thread.
    """

    def __init__(self) -> None:
        # Each entry is (queue, loop) so broadcast() always dispatches to the
        # loop that owns the queue, regardless of which thread calls broadcast().
        self._subscribers: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []
        # Lock guards _subscribers against concurrent subscribe/unsubscribe while
        # broadcast() may be taking a snapshot.
        self._lock = threading.Lock()

    def subscribe(self, maxsize: int = 0) -> asyncio.Queue:
        # Capture the running loop at subscription time — the worker thread that
        # calls broadcast() later may be on a different loop entirely.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. in sync tests); fall back gracefully.
            loop = asyncio.new_event_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append((queue, loop))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = [(q, l) for q, l in self._subscribers if q is not queue]

    def broadcast(self, event: str, data: dict[str, Any]) -> None:
        message = {
            "event": event,
            "data": json.dumps(data, ensure_ascii=False),
        }
        # Take a snapshot so subscribe/unsubscribe during iteration is safe.
        with self._lock:
            snapshot = list(self._subscribers)
        for queue, loop in snapshot:
            try:
                if loop.is_running():
                    loop.call_soon_threadsafe(queue.put_nowait, message)
                else:
                    # No running loop (e.g. in tests), fall back to direct put
                    queue.put_nowait(message)
            except (asyncio.QueueFull, RuntimeError):
                pass  # Drop if consumer is slow or loop is closed


# Module-level singleton
_bus = SSEBus()


def subscribe() -> asyncio.Queue:
    return _bus.subscribe()


def unsubscribe(queue: asyncio.Queue) -> None:
    _bus.unsubscribe(queue)


def broadcast_job_event(event_type: str, job_data: dict[str, Any]) -> None:
    """Broadcast a job event to all SSE subscribers."""
    _bus.broadcast(event_type, job_data)
