"""Tests for the Ruflo hook bridge (broker/hooks.py).

Starts a real broker server on a random port and verifies that
hook functions correctly capture events to the broker.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import HTTPServer

from broker.config import BrokerConfig, BackendConfig
from broker.engine import BrokerEngine
from broker.hooks import capture_post_task, capture_post_edit, capture_session_event
from broker.server import BrokerHandler


def _start_server(engine: BrokerEngine) -> tuple[HTTPServer, str]:
    BrokerHandler.engine = engine
    server = HTTPServer(("127.0.0.1", 0), BrokerHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


class TestHookBridge(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cfg = BrokerConfig(
            user_id="hooktest",
            workspace_id="hookws",
            local_cache_path=cls._tmpdir,
            supermemory=BackendConfig(enabled=False),
            ruflo=BackendConfig(enabled=False),
            local_cache=BackendConfig(enabled=True),
        )
        cfg.write_policy = {
            "procedural": ["local_cache"],
            "episodic": ["local_cache"],
        }
        cfg.retrieval_limits = {"procedural": 10, "episodic": 10}
        cls.engine = BrokerEngine(cfg)
        cls.server, cls.base = _start_server(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_capture_post_task(self):
        result = capture_post_task(
            task_id="hook-test-001",
            task_description="Test task via hook bridge",
            success=True,
            quality=0.9,
            broker_url=self.base,
        )
        self.assertIn("event_id", result)
        self.assertIn("record_id", result)
        self.assertEqual(result["decision"]["scope"], "procedural")
        self.assertIn("local_cache", result["backend_results"])

    def test_capture_post_task_failed(self):
        result = capture_post_task(
            task_id="hook-test-002",
            task_description="Failed task",
            success=False,
            quality=0.3,
            broker_url=self.base,
        )
        self.assertIn("event_id", result)
        self.assertIn("failed", result["backend_results"]["local_cache"]["content"])

    def test_capture_post_edit(self):
        result = capture_post_edit(
            file_path="broker/engine.py",
            success=True,
            broker_url=self.base,
        )
        self.assertIn("event_id", result)
        self.assertEqual(result["decision"]["scope"], "episodic")

    def test_capture_session_start(self):
        result = capture_session_event(
            event_type="start",
            session_id="sess-test-001",
            broker_url=self.base,
        )
        self.assertIn("event_id", result)
        self.assertIn("start", result["backend_results"]["local_cache"]["content"])

    def test_capture_session_end(self):
        result = capture_session_event(
            event_type="end",
            session_id="sess-test-001",
            broker_url=self.base,
        )
        self.assertIn("event_id", result)

    def test_unreachable_broker(self):
        result = capture_post_task(
            task_id="unreachable",
            broker_url="http://127.0.0.1:1",  # nothing listening
        )
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
