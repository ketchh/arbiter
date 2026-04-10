"""End-to-end broker round-trip tests.

Tests normalize → capture → retrieve against temp backends.
No real .swarm/memory.db or Supermemory API calls.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from broker.config import BrokerConfig, BackendConfig
from broker.engine import BrokerEngine
from broker.schema import (
    BrokerEvent,
    MemoryRecord,
    MemoryScope,
    MemoryType,
    Provenance,
    clamp_unit,
    normalize_client_event,
)
from broker.policy import WriteDecision, evaluate_write


class TestClampUnit(unittest.TestCase):
    def test_in_range(self):
        self.assertEqual(clamp_unit(0.5, "x"), 0.5)

    def test_below_zero(self):
        self.assertEqual(clamp_unit(-0.1, "x"), 0.0)

    def test_above_one(self):
        self.assertEqual(clamp_unit(1.5, "x"), 1.0)

    def test_boundary(self):
        self.assertEqual(clamp_unit(0.0, "x"), 0.0)
        self.assertEqual(clamp_unit(1.0, "x"), 1.0)


class TestNormalizeClientEvent(unittest.TestCase):
    def test_basic_normalization(self):
        raw = {
            "scope": "project",
            "memory_type": "decision",
            "subject": "test",
            "content": "hello",
            "confidence": 0.9,
            "importance": 0.8,
        }
        event = normalize_client_event(raw, "test-client", "user1", "ws1")
        self.assertEqual(event.scope, MemoryScope.PROJECT)
        self.assertEqual(event.memory_type, MemoryType.DECISION)
        self.assertEqual(event.client, "test-client")
        self.assertEqual(event.user_id, "user1")
        self.assertEqual(event.workspace_id, "ws1")
        self.assertAlmostEqual(event.confidence, 0.9)
        self.assertAlmostEqual(event.importance, 0.8)

    def test_defaults(self):
        event = normalize_client_event({}, "c", "u", "w")
        self.assertEqual(event.scope, MemoryScope.EPISODIC)
        self.assertEqual(event.memory_type, MemoryType.FACT)

    def test_camelcase_memory_type(self):
        raw = {"memoryType": "workflow"}
        event = normalize_client_event(raw, "c", "u", "w")
        self.assertEqual(event.memory_type, MemoryType.WORKFLOW)

    def test_clamping(self):
        raw = {"confidence": 2.0, "importance": -1.0}
        event = normalize_client_event(raw, "c", "u", "w")
        self.assertAlmostEqual(event.confidence, 1.0)
        self.assertAlmostEqual(event.importance, 0.0)


class TestPolicy(unittest.TestCase):
    def _make_config(self) -> BrokerConfig:
        cfg = BrokerConfig()
        cfg.write_policy = {
            "profile": ["supermemory", "local_cache"],
            "project": ["supermemory", "ruflo", "local_cache"],
            "episodic": ["supermemory", "ruflo", "local_cache"],
            "procedural": ["supermemory", "ruflo", "local_cache"],
            "governance": ["supermemory", "local_cache"],
        }
        return cfg

    def test_standard_routing(self):
        cfg = self._make_config()
        event = BrokerEvent(scope=MemoryScope.PROJECT, importance=0.8)
        decision = evaluate_write(event, cfg)
        self.assertIn("supermemory", decision.backends)
        self.assertIn("ruflo", decision.backends)

    def test_low_importance_episodic_skips_supermemory(self):
        cfg = self._make_config()
        event = BrokerEvent(scope=MemoryScope.EPISODIC, importance=0.2)
        decision = evaluate_write(event, cfg)
        self.assertNotIn("supermemory", decision.backends)
        self.assertIn("ruflo", decision.backends)

    def test_empty_policy_blocks(self):
        cfg = BrokerConfig()
        cfg.write_policy = {}
        event = BrokerEvent(scope=MemoryScope.PROFILE, importance=0.9)
        decision = evaluate_write(event, cfg)
        self.assertEqual(decision.backends, [])


class TestLocalCacheRoundTrip(unittest.TestCase):
    def test_upsert_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = BrokerConfig(
                user_id="testuser",
                workspace_id="testws",
                local_cache_path=tmpdir,
                supermemory=BackendConfig(enabled=False),
                ruflo=BackendConfig(enabled=False),
                local_cache=BackendConfig(enabled=True),
            )
            cfg.write_policy = {
                "project": ["local_cache"],
            }
            cfg.retrieval_limits = {"project": 10}

            engine = BrokerEngine(cfg)

            raw = {
                "scope": "project",
                "memory_type": "decision",
                "subject": "test:roundtrip",
                "content": "This is a round-trip test.",
                "confidence": 0.95,
                "importance": 0.85,
            }
            event = engine.normalize(raw, client_name="test")
            result = engine.capture_event(event, dry_run=False)

            self.assertEqual(
                result.backend_results["local_cache"]["scope"], "project"
            )

            retrieved = engine.retrieve_context(
                query="round-trip", scope_filters=["project"]
            )
            self.assertTrue(len(retrieved) > 0)
            self.assertEqual(retrieved[0].backend_source, "local_cache")
            self.assertTrue(len(retrieved[0].records) > 0)
            self.assertEqual(
                retrieved[0].records[0]["content"], "This is a round-trip test."
            )


class TestRufloRoundTrip(unittest.TestCase):
    def test_upsert_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_memory.db")

            cfg = BrokerConfig(
                user_id="testuser",
                workspace_id="testws",
                supermemory=BackendConfig(enabled=False),
                ruflo=BackendConfig(enabled=True),
                local_cache=BackendConfig(enabled=False),
            )
            cfg.write_policy = {
                "episodic": ["ruflo"],
            }
            cfg.retrieval_limits = {"episodic": 10}

            # Patch env for ruflo DB path
            old_val = os.environ.get("RUFLO_DB_PATH")
            os.environ["RUFLO_DB_PATH"] = db_path
            try:
                engine = BrokerEngine(cfg)

                raw = {
                    "scope": "episodic",
                    "memory_type": "episode",
                    "subject": "test:ruflo",
                    "content": "Ruflo round-trip test.",
                    "confidence": 0.7,
                    "importance": 0.6,
                }
                event = engine.normalize(raw, client_name="test")
                result = engine.capture_event(event, dry_run=False)

                self.assertEqual(result.backend_results["ruflo"]["status"], "OK")

                retrieved = engine.retrieve_context(
                    query="ruflo test", scope_filters=["episodic"]
                )
                self.assertTrue(len(retrieved) > 0)
                self.assertEqual(retrieved[0].backend_source, "ruflo")
                records = retrieved[0].records
                self.assertTrue(len(records) > 0)
                self.assertEqual(records[0]["content"], "Ruflo round-trip test.")
            finally:
                if old_val is None:
                    os.environ.pop("RUFLO_DB_PATH", None)
                else:
                    os.environ["RUFLO_DB_PATH"] = old_val


class TestSupermemoryStubBehavior(unittest.TestCase):
    """Test that Supermemory adapter degrades gracefully without API key."""

    def test_no_key_upsert_returns_no_key(self):
        from broker.adapters.supermemory import SupermemoryBackend

        backend = SupermemoryBackend(api_key="", base_url="")
        record = MemoryRecord(
            scope=MemoryScope.PROJECT,
            content="test",
        )
        result = backend.upsert(record)
        self.assertEqual(result["status"], "NO_KEY")

    def test_no_key_retrieve_returns_empty(self):
        from broker.adapters.supermemory import SupermemoryBackend

        backend = SupermemoryBackend(api_key="", base_url="")
        results = backend.retrieve("project", "user", "ws", limit=5)
        self.assertEqual(results, [])


class TestServerEndpoints(unittest.TestCase):
    """Test the HTTP server handler logic via direct calls."""

    def test_health_endpoint(self):
        import io
        from http.server import BaseHTTPRequestHandler
        from broker.server import BrokerHandler, _json_response

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = BrokerConfig(
                local_cache_path=tmpdir,
                supermemory=BackendConfig(enabled=False),
                ruflo=BackendConfig(enabled=False),
                local_cache=BackendConfig(enabled=True),
            )
            engine = BrokerEngine(cfg)
            BrokerHandler.engine = engine

            # Verify engine has local_cache backend
            self.assertIn("local_cache", engine._backends)


class TestDryRun(unittest.TestCase):
    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = BrokerConfig(
                user_id="testuser",
                workspace_id="testws",
                local_cache_path=tmpdir,
                supermemory=BackendConfig(enabled=False),
                ruflo=BackendConfig(enabled=False),
                local_cache=BackendConfig(enabled=True),
            )
            cfg.write_policy = {"project": ["local_cache"]}
            cfg.retrieval_limits = {"project": 10}

            engine = BrokerEngine(cfg)

            raw = {
                "scope": "project",
                "content": "should not persist",
                "importance": 0.9,
            }
            event = engine.normalize(raw, client_name="test")
            result = engine.capture_event(event, dry_run=True)

            self.assertEqual(
                result.backend_results["local_cache"]["status"], "DRY_RUN"
            )

            retrieved = engine.retrieve_context(
                query="persist", scope_filters=["project"]
            )
            # No records should exist since dry_run=True
            total_records = sum(len(r.records) for r in retrieved)
            self.assertEqual(total_records, 0)


if __name__ == "__main__":
    unittest.main()
