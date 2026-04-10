"""Multi-workspace isolation tests.

Proves that two workspaces writing to the same backends get properly
separated results on retrieve.  No real Supermemory API calls.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from broker.config import BrokerConfig, BackendConfig
from broker.engine import BrokerEngine
from broker.adapters.supermemory import SupermemoryBackend
from broker.schema import MemoryRecord, MemoryScope, MemoryType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(
    *,
    user_id: str,
    workspace_id: str,
    cache_dir: str | None = None,
    ruflo_db: str | None = None,
) -> BrokerEngine:
    """Build a BrokerEngine with only the requested backends enabled."""
    cfg = BrokerConfig(
        user_id=user_id,
        workspace_id=workspace_id,
        local_cache_path=cache_dir or "",
        supermemory=BackendConfig(enabled=False),
        ruflo=BackendConfig(enabled=bool(ruflo_db)),
        local_cache=BackendConfig(enabled=bool(cache_dir)),
    )
    # Policy: route project and episodic to whichever backends are on.
    targets = []
    if cache_dir:
        targets.append("local_cache")
    if ruflo_db:
        targets.append("ruflo")
    cfg.write_policy = {
        "project": list(targets),
        "episodic": list(targets),
    }
    cfg.retrieval_limits = {"project": 50, "episodic": 50}
    return cfg, targets


def _capture(engine: BrokerEngine, scope: str, content: str, subject: str = "iso-test") -> None:
    """Shorthand: normalize + capture a single event."""
    raw = {
        "scope": scope,
        "memory_type": "decision",
        "subject": subject,
        "content": content,
        "confidence": 0.9,
        "importance": 0.8,
    }
    event = engine.normalize(raw, client_name="test")
    result = engine.capture_event(event, dry_run=False)
    # Sanity: at least one backend wrote successfully.
    for name, res in result.backend_results.items():
        assert res.get("status") in ("OK", "ok", None) or "scope" in res, (
            f"Backend {name} failed: {res}"
        )


# ---------------------------------------------------------------------------
# 1. Local cache isolation
# ---------------------------------------------------------------------------

class TestLocalCacheIsolation(unittest.TestCase):
    """Two engines sharing the same cache dir but different workspace_ids."""

    def test_each_workspace_sees_only_its_own_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_a, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", cache_dir=tmpdir)
            cfg_b, _ = _make_engine(user_id="user1", workspace_id="ws-beta", cache_dir=tmpdir)
            engine_a = BrokerEngine(cfg_a)
            engine_b = BrokerEngine(cfg_b)

            _capture(engine_a, "project", "Alpha architecture note")
            _capture(engine_b, "project", "Beta architecture note")

            ret_a = engine_a.retrieve_context(query="architecture", scope_filters=["project"])
            ret_b = engine_b.retrieve_context(query="architecture", scope_filters=["project"])

            records_a = [r for rr in ret_a for r in rr.records]
            records_b = [r for rr in ret_b for r in rr.records]

            self.assertTrue(len(records_a) > 0, "ws-alpha should find its own record")
            self.assertTrue(len(records_b) > 0, "ws-beta should find its own record")

            for r in records_a:
                self.assertEqual(r["workspace_id"], "ws-alpha",
                                 "ws-alpha must not see ws-beta records")
            for r in records_b:
                self.assertEqual(r["workspace_id"], "ws-beta",
                                 "ws-beta must not see ws-alpha records")

    def test_different_users_same_workspace_isolated(self):
        """Even within the same workspace, user_id filtering applies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_a, _ = _make_engine(user_id="alice", workspace_id="ws-shared", cache_dir=tmpdir)
            cfg_b, _ = _make_engine(user_id="bob", workspace_id="ws-shared", cache_dir=tmpdir)
            engine_a = BrokerEngine(cfg_a)
            engine_b = BrokerEngine(cfg_b)

            _capture(engine_a, "project", "Alice secret note")
            _capture(engine_b, "project", "Bob secret note")

            ret_a = engine_a.retrieve_context(query="secret", scope_filters=["project"])
            records_a = [r for rr in ret_a for r in rr.records]

            for r in records_a:
                self.assertEqual(r["user_id"], "alice",
                                 "Alice must not see Bob's records")


# ---------------------------------------------------------------------------
# 2. Ruflo sqlite isolation
# ---------------------------------------------------------------------------

class TestRufloSqliteIsolation(unittest.TestCase):
    """Two engines sharing the same sqlite DB but different workspace_ids."""

    def test_each_workspace_sees_only_its_own_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "shared_memory.db")

            cfg_a, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", ruflo_db=db_path)
            cfg_b, _ = _make_engine(user_id="user1", workspace_id="ws-beta", ruflo_db=db_path)

            old_val = os.environ.get("RUFLO_DB_PATH")
            os.environ["RUFLO_DB_PATH"] = db_path
            try:
                engine_a = BrokerEngine(cfg_a)
                engine_b = BrokerEngine(cfg_b)

                _capture(engine_a, "episodic", "Alpha session log")
                _capture(engine_b, "episodic", "Beta session log")

                ret_a = engine_a.retrieve_context(query="session", scope_filters=["episodic"])
                ret_b = engine_b.retrieve_context(query="session", scope_filters=["episodic"])

                records_a = [r for rr in ret_a for r in rr.records]
                records_b = [r for rr in ret_b for r in rr.records]

                self.assertTrue(len(records_a) > 0, "ws-alpha should find its record")
                self.assertTrue(len(records_b) > 0, "ws-beta should find its record")

                for r in records_a:
                    self.assertEqual(r["workspace_id"], "ws-alpha")
                for r in records_b:
                    self.assertEqual(r["workspace_id"], "ws-beta")
            finally:
                if old_val is None:
                    os.environ.pop("RUFLO_DB_PATH", None)
                else:
                    os.environ["RUFLO_DB_PATH"] = old_val

    def test_multiple_scopes_isolated(self):
        """Records in different scopes also respect workspace boundaries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "shared_memory.db")

            cfg_a, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", ruflo_db=db_path)
            cfg_b, _ = _make_engine(user_id="user1", workspace_id="ws-beta", ruflo_db=db_path)

            old_val = os.environ.get("RUFLO_DB_PATH")
            os.environ["RUFLO_DB_PATH"] = db_path
            try:
                engine_a = BrokerEngine(cfg_a)
                engine_b = BrokerEngine(cfg_b)

                _capture(engine_a, "project", "Alpha project decision")
                _capture(engine_b, "episodic", "Beta episodic entry")

                # ws-alpha retrieves episodic -- should get nothing (it only wrote to project)
                ret = engine_a.retrieve_context(query="", scope_filters=["episodic"])
                records = [r for rr in ret for r in rr.records]
                for r in records:
                    self.assertEqual(r["workspace_id"], "ws-alpha",
                                     "Must not leak ws-beta episodic records to ws-alpha")
            finally:
                if old_val is None:
                    os.environ.pop("RUFLO_DB_PATH", None)
                else:
                    os.environ["RUFLO_DB_PATH"] = old_val


# ---------------------------------------------------------------------------
# 3. Supermemory container tag isolation (unit test, no API call)
# ---------------------------------------------------------------------------

class TestSupermemoryContainerTagIsolation(unittest.TestCase):
    """Verify _container_tag_for_scope() produces different tags per workspace."""

    def setUp(self):
        self.backend = SupermemoryBackend(api_key="", base_url="")

    def test_different_workspaces_different_tags(self):
        tag_alpha = self.backend._container_tag_for_scope("project", "alpha")
        tag_beta = self.backend._container_tag_for_scope("project", "beta")
        self.assertNotEqual(tag_alpha, tag_beta,
                            "Different workspaces must produce different container tags")

    def test_expected_tag_format(self):
        tag = self.backend._container_tag_for_scope("project", "alpha")
        self.assertEqual(tag, "broker-alpha-project")

        tag2 = self.backend._container_tag_for_scope("episodic", "beta")
        self.assertEqual(tag2, "broker-beta-episodic")

    def test_same_workspace_same_scope_same_tag(self):
        tag1 = self.backend._container_tag_for_scope("governance", "ws-1")
        tag2 = self.backend._container_tag_for_scope("governance", "ws-1")
        self.assertEqual(tag1, tag2)

    def test_same_workspace_different_scope_different_tag(self):
        tag_proj = self.backend._container_tag_for_scope("project", "alpha")
        tag_epi = self.backend._container_tag_for_scope("episodic", "alpha")
        self.assertNotEqual(tag_proj, tag_epi)

    def test_empty_workspace_still_valid(self):
        tag = self.backend._container_tag_for_scope("project", "")
        self.assertEqual(tag, "broker-project",
                         "Empty workspace should produce tag without double-dash")

    def test_record_level_container_tag(self):
        """Verify _container_tag() on a MemoryRecord also respects workspace."""
        rec_a = MemoryRecord(
            scope=MemoryScope.PROJECT,
            workspace_id="alpha",
            content="test",
        )
        rec_b = MemoryRecord(
            scope=MemoryScope.PROJECT,
            workspace_id="beta",
            content="test",
        )
        tag_a = self.backend._container_tag(rec_a)
        tag_b = self.backend._container_tag(rec_b)
        self.assertNotEqual(tag_a, tag_b)
        self.assertEqual(tag_a, "broker-alpha-project")
        self.assertEqual(tag_b, "broker-beta-project")


# ---------------------------------------------------------------------------
# 4. Cross-workspace leakage test
# ---------------------------------------------------------------------------

class TestCrossWorkspaceLeakage(unittest.TestCase):
    """Write from ws-alpha, retrieve as ws-beta -- must get nothing."""

    def test_local_cache_no_leakage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_a, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", cache_dir=tmpdir)
            cfg_b, _ = _make_engine(user_id="user1", workspace_id="ws-beta", cache_dir=tmpdir)
            engine_a = BrokerEngine(cfg_a)
            engine_b = BrokerEngine(cfg_b)

            _capture(engine_a, "project", "Alpha-only content marker-xyz")

            ret_b = engine_b.retrieve_context(query="marker-xyz", scope_filters=["project"])
            records_b = [r for rr in ret_b for r in rr.records]
            self.assertEqual(len(records_b), 0,
                             "ws-beta must NOT see ws-alpha records")

    def test_ruflo_no_leakage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "shared_memory.db")

            cfg_a, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", ruflo_db=db_path)
            cfg_b, _ = _make_engine(user_id="user1", workspace_id="ws-beta", ruflo_db=db_path)

            old_val = os.environ.get("RUFLO_DB_PATH")
            os.environ["RUFLO_DB_PATH"] = db_path
            try:
                engine_a = BrokerEngine(cfg_a)
                engine_b = BrokerEngine(cfg_b)

                _capture(engine_a, "episodic", "Alpha-only secret marker-abc")

                ret_b = engine_b.retrieve_context(query="marker-abc", scope_filters=["episodic"])
                records_b = [r for rr in ret_b for r in rr.records]
                self.assertEqual(len(records_b), 0,
                                 "ws-beta must NOT see ws-alpha records via ruflo")
            finally:
                if old_val is None:
                    os.environ.pop("RUFLO_DB_PATH", None)
                else:
                    os.environ["RUFLO_DB_PATH"] = old_val

    def test_leakage_across_both_backends(self):
        """Write to both backends from ws-alpha, retrieve as ws-beta from both."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "shared_memory.db")
            cache_dir = tmpdir

            cfg_a, _ = _make_engine(
                user_id="user1", workspace_id="ws-alpha",
                cache_dir=cache_dir, ruflo_db=db_path,
            )
            cfg_b, _ = _make_engine(
                user_id="user1", workspace_id="ws-beta",
                cache_dir=cache_dir, ruflo_db=db_path,
            )

            old_val = os.environ.get("RUFLO_DB_PATH")
            os.environ["RUFLO_DB_PATH"] = db_path
            try:
                engine_a = BrokerEngine(cfg_a)
                engine_b = BrokerEngine(cfg_b)

                _capture(engine_a, "project", "Dual-backend alpha-only marker-dual")

                ret_b = engine_b.retrieve_context(query="marker-dual", scope_filters=["project"])
                records_b = [r for rr in ret_b for r in rr.records]
                self.assertEqual(len(records_b), 0,
                                 "ws-beta must NOT see ws-alpha records from any backend")
            finally:
                if old_val is None:
                    os.environ.pop("RUFLO_DB_PATH", None)
                else:
                    os.environ["RUFLO_DB_PATH"] = old_val


# ---------------------------------------------------------------------------
# 5. Same-workspace retrieval
# ---------------------------------------------------------------------------

class TestSameWorkspaceRetrieval(unittest.TestCase):
    """Write and retrieve from the same workspace -- records must be found."""

    def test_local_cache_same_workspace_finds_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", cache_dir=tmpdir)
            engine = BrokerEngine(cfg)

            _capture(engine, "project", "Alpha project finding marker-found")

            ret = engine.retrieve_context(query="marker-found", scope_filters=["project"])
            records = [r for rr in ret for r in rr.records]
            self.assertTrue(len(records) > 0, "Same workspace must find its own records")
            self.assertEqual(records[0]["content"], "Alpha project finding marker-found")

    def test_ruflo_same_workspace_finds_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test_memory.db")

            cfg, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", ruflo_db=db_path)

            old_val = os.environ.get("RUFLO_DB_PATH")
            os.environ["RUFLO_DB_PATH"] = db_path
            try:
                engine = BrokerEngine(cfg)

                _capture(engine, "episodic", "Alpha episodic marker-ep")

                ret = engine.retrieve_context(query="marker-ep", scope_filters=["episodic"])
                records = [r for rr in ret for r in rr.records]
                self.assertTrue(len(records) > 0, "Same workspace must find its own records")
                self.assertEqual(records[0]["content"], "Alpha episodic marker-ep")
            finally:
                if old_val is None:
                    os.environ.pop("RUFLO_DB_PATH", None)
                else:
                    os.environ["RUFLO_DB_PATH"] = old_val

    def test_multiple_records_same_workspace(self):
        """Write several records, verify all are retrieved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg, _ = _make_engine(user_id="user1", workspace_id="ws-alpha", cache_dir=tmpdir)
            engine = BrokerEngine(cfg)

            for i in range(5):
                _capture(engine, "project", f"Record number {i} batchtest")

            ret = engine.retrieve_context(query="batchtest", scope_filters=["project"])
            records = [r for rr in ret for r in rr.records]
            self.assertEqual(len(records), 5,
                             "All 5 records should be retrieved for the same workspace")


if __name__ == "__main__":
    unittest.main()
