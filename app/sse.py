"""Server-Sent Events broadcast bus for job status updates."""

import asyncio
import json
from typing import Any


class SSEBus:
    """Simple pub/sub bus for SSE job events.

    Thread-safe: broadcast() can be called from any thread.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get the running event loop (cached after first call)."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.get_event_loop()
        return self._loop

    def subscribe(self, maxsize: int = 0) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def broadcast(self, event: str, data: dict[str, Any]) -> None:
        message = {
            "event": event,
            "data": json.dumps(data, ensure_ascii=False),
        }
        for queue in self._subscribers:
            try:
                loop = self._get_loop()
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
