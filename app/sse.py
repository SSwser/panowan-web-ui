"""Server-Sent Events broadcast bus for job status updates."""

import asyncio
import json
from typing import Any


class SSEBus:
    """Simple pub/sub bus for SSE job events."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

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
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # Drop if consumer is slow


# Module-level singleton
_bus = SSEBus()


def subscribe() -> asyncio.Queue:
    return _bus.subscribe()


def unsubscribe(queue: asyncio.Queue) -> None:
    _bus.unsubscribe(queue)


def broadcast_job_event(event_type: str, job_data: dict[str, Any]) -> None:
    """Broadcast a job event to all SSE subscribers."""
    _bus.broadcast(event_type, job_data)
