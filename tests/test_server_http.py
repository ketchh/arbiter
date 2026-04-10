"""HTTP-level tests for the broker server.

Spins up a real server on a random port and exercises all endpoints
with actual HTTP requests, including auth enforcement.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

from broker.config import BrokerConfig, BackendConfig
from broker.engine import BrokerEngine
from broker.server import BrokerHandler, _API_KEY


def _start_server(engine: BrokerEngine) -> tuple[HTTPServer, str]:
    """Start a broker server on a random port, return (server, base_url)."""
    BrokerHandler.engine = engine
    server = HTTPServer(("127.0.0.1", 0), BrokerHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


def _request(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict]:
    """Make an HTTP request and return (status, json_body)."""
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


class TestServerHTTP(unittest.TestCase):
    """Full HTTP round-trip tests against a live local server."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cfg = BrokerConfig(
            user_id="httptest",
            workspace_id="httpws",
            local_cache_path=cls._tmpdir,
            supermemory=BackendConfig(enabled=False),
            ruflo=BackendConfig(enabled=False),
            local_cache=BackendConfig(enabled=True),
        )
        cfg.write_policy = {
            "project": ["local_cache"],
            "episodic": ["local_cache"],
        }
        cfg.retrieval_limits = {"project": 10, "episodic": 10}
        cls.engine = BrokerEngine(cfg)
        cls.server, cls.base = _start_server(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_health(self):
        status, body = _request(f"{self.base}/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_404(self):
        status, body = _request(f"{self.base}/nonexistent")
        self.assertEqual(status, 404)

    def test_capture_and_retrieve(self):
        # Capture
        status, body = _request(f"{self.base}/capture", "POST", {
            "client": "test-http",
            "scope": "project",
            "memory_type": "decision",
            "subject": "http-test",
            "content": "HTTP round-trip test content.",
            "confidence": 0.9,
            "importance": 0.8,
        })
        self.assertEqual(status, 200)
        self.assertIn("event_id", body)
        self.assertIn("record_id", body)
        self.assertIn("local_cache", body["backend_results"])

        # Retrieve
        status, body = _request(f"{self.base}/retrieve", "POST", {
            "query": "http round-trip",
            "scope_filters": ["project"],
        })
        self.assertEqual(status, 200)
        results = body["results"]
        self.assertTrue(len(results) > 0)
        records = results[0]["records"]
        self.assertTrue(any(
            "HTTP round-trip" in r.get("content", "") for r in records
        ))

    def test_explain(self):
        status, body = _request(f"{self.base}/explain", "POST", {
            "query": "test",
            "scope_filters": ["project"],
        })
        self.assertEqual(status, 200)
        self.assertIn("scopes_queried", body)
        self.assertIn("backends_consulted", body)

    def test_upsert(self):
        status, body = _request(f"{self.base}/upsert", "POST", {
            "scope": "episodic",
            "memory_type": "episode",
            "content": "Direct upsert test.",
            "importance": 0.7,
        })
        self.assertEqual(status, 200)
        self.assertIn("record_id", body)

    def test_flush_cache(self):
        status, body = _request(f"{self.base}/cache", "DELETE")
        self.assertEqual(status, 200)
        self.assertIn("flushed", body)

    def test_invalid_json(self):
        req = urllib.request.Request(
            f"{self.base}/capture",
            data=b"not json",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode())
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_options_cors(self):
        req = urllib.request.Request(
            f"{self.base}/capture",
            method="OPTIONS",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 204)
            allow_headers = resp.headers.get("Access-Control-Allow-Headers", "")
            self.assertIn("Authorization", allow_headers)


class TestServerAuth(unittest.TestCase):
    """Test auth enforcement when BROKER_API_KEY is set."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cfg = BrokerConfig(
            local_cache_path=cls._tmpdir,
            supermemory=BackendConfig(enabled=False),
            ruflo=BackendConfig(enabled=False),
            local_cache=BackendConfig(enabled=True),
        )
        cfg.write_policy = {"project": ["local_cache"]}
        cfg.retrieval_limits = {"project": 10}
        cls.engine = BrokerEngine(cfg)

        # Patch the module-level _API_KEY
        import broker.server as srv
        cls._original_key = srv._API_KEY
        srv._API_KEY = "test-secret-key"

        cls.server, cls.base = _start_server(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        import broker.server as srv
        srv._API_KEY = cls._original_key

    def test_health_no_auth_required(self):
        status, body = _request(f"{self.base}/health")
        self.assertEqual(status, 200)

    def test_capture_rejected_without_key(self):
        status, body = _request(f"{self.base}/capture", "POST", {
            "scope": "project", "content": "test",
        })
        self.assertEqual(status, 401)

    def test_capture_accepted_with_key(self):
        status, body = _request(
            f"{self.base}/capture", "POST",
            {"scope": "project", "content": "authed test"},
            headers={"Authorization": "Bearer test-secret-key"},
        )
        self.assertEqual(status, 200)

    def test_retrieve_rejected_without_key(self):
        status, body = _request(f"{self.base}/retrieve", "POST", {
            "query": "test",
        })
        self.assertEqual(status, 401)

    def test_delete_rejected_without_key(self):
        status, body = _request(f"{self.base}/cache", "DELETE")
        self.assertEqual(status, 401)


class TestMetricsEndpoint(unittest.TestCase):
    """Test /metrics endpoint."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cfg = BrokerConfig(
            local_cache_path=cls._tmpdir,
            supermemory=BackendConfig(enabled=False),
            ruflo=BackendConfig(enabled=False),
            local_cache=BackendConfig(enabled=True),
        )
        cfg.write_policy = {"project": ["local_cache"]}
        cfg.retrieval_limits = {"project": 10}
        cls.engine = BrokerEngine(cfg)
        cls.server, cls.base = _start_server(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_metrics_returns_counters(self):
        # Make a request first so metrics have something
        _request(f"{self.base}/health")
        status, body = _request(f"{self.base}/metrics")
        self.assertEqual(status, 200)
        self.assertIn("total_requests", body)
        self.assertIn("uptime_seconds", body)
        self.assertIn("by_path", body)
        self.assertIn("by_status", body)
        self.assertGreater(body["total_requests"], 0)


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting enforcement."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cfg = BrokerConfig(
            local_cache_path=cls._tmpdir,
            supermemory=BackendConfig(enabled=False),
            ruflo=BackendConfig(enabled=False),
            local_cache=BackendConfig(enabled=True),
        )
        cfg.write_policy = {"project": ["local_cache"]}
        cfg.retrieval_limits = {"project": 10}
        cls.engine = BrokerEngine(cfg)

        # Set a very low rate limit for testing
        import broker.server as srv
        cls._orig_limiter = srv._rate_limiter
        srv._rate_limiter = srv._RateLimiter(max_requests=3, window_seconds=60)

        cls.server, cls.base = _start_server(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        import broker.server as srv
        srv._rate_limiter = cls._orig_limiter

    def test_rate_limit_enforcement(self):
        # First 3 requests should succeed
        for i in range(3):
            status, _ = _request(f"{self.base}/capture", "POST", {
                "scope": "project", "content": f"rate test {i}",
            })
            self.assertEqual(status, 200, f"Request {i} should succeed")

        # 4th request should be rate limited
        status, body = _request(f"{self.base}/capture", "POST", {
            "scope": "project", "content": "should be blocked",
        })
        self.assertEqual(status, 429)
        self.assertEqual(body["error"], "rate limit exceeded")


if __name__ == "__main__":
    unittest.main()
