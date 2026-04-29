import asyncio
import json
import unittest

from app.sse import SSEBus


class SSEBusTests(unittest.TestCase):
    def test_subscribe_returns_queue(self) -> None:
        bus = SSEBus()
        queue = bus.subscribe()
        self.assertIsInstance(queue, asyncio.Queue)

    def test_broadcast_delivers_to_all_subscribers(self) -> None:
        bus = SSEBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.broadcast("job_updated", {"job_id": "test", "status": "running"})
        msg1 = q1.get_nowait()
        msg2 = q2.get_nowait()
        self.assertEqual(msg1["event"], "job_updated")
        self.assertEqual(json.loads(msg1["data"])["job_id"], "test")
        self.assertEqual(msg2["event"], "job_updated")

    def test_unsubscribe_removes_queue(self) -> None:
        bus = SSEBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.broadcast("job_updated", {"job_id": "test"})
        self.assertTrue(q.empty())

    def test_broadcast_after_unsubscribe_only_reaches_active(self) -> None:
        bus = SSEBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.unsubscribe(q1)
        bus.broadcast("job_updated", {"job_id": "test"})
        self.assertTrue(q1.empty())
        self.assertFalse(q2.empty())

    def test_broadcast_drops_on_full_queue(self) -> None:
        bus = SSEBus()
        q = bus.subscribe(maxsize=1)
        bus.broadcast("event1", {"a": 1})
        # Queue is now full (maxsize=1), next broadcast should be dropped
        bus.broadcast("event2", {"a": 2})
        msg = q.get_nowait()
        self.assertEqual(json.loads(msg["data"])["a"], 1)
        self.assertTrue(q.empty())  # event2 was dropped
