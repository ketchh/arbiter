"""Ruflo adapter — reads/writes directly to .swarm/memory.db via sqlite3.

Uses the same schema that Ruflo MCP creates (memory_entries table),
so broker records and Ruflo MCP tools coexist on the same database.

Namespace convention:  broker scope value  ->  memory_entries.namespace
Key convention:        broker:<scope>:<record_id>
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from broker.schema import MemoryRecord, MemoryScope

log = logging.getLogger(__name__)


def _escape_like(s: str) -> str:
    """Escape LIKE-special characters so user input is treated literally."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Ruflo's memory_entries.type enum — "semantic" is the safest generic choice.
_RUFLO_TYPE_MAP: dict[str, str] = {
    "profile": "semantic",
    "project": "semantic",
    "episodic": "episodic",
    "procedural": "procedural",
    "governance": "semantic",
}


class RufloBackend:
    """Ruflo working memory — sqlite3 adapter for .swarm/memory.db."""

    name = "ruflo"

    def __init__(
        self,
        data_path: str = ".swarm/memory.db",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.db_path = Path(data_path)
        self.extra = extra or {}
        self._ensure_db()

    # -- internal helpers --------------------------------------------------

    def _ensure_db(self) -> None:
        """Verify the DB and memory_entries table exist; set WAL mode once."""
        if not self.db_path.is_file():
            log.warning("[ruflo] DB not found at %s — creating empty DB", self.db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            # WAL mode persists once set — only needs to run at init time.
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    namespace TEXT DEFAULT 'default',
                    content TEXT NOT NULL,
                    type TEXT DEFAULT 'semantic',
                    embedding TEXT,
                    embedding_model TEXT DEFAULT 'local',
                    embedding_dimensions INTEGER,
                    tags TEXT,
                    metadata TEXT,
                    owner_id TEXT,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now') * 1000),
                    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now') * 1000),
                    expires_at INTEGER,
                    last_accessed_at INTEGER,
                    access_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    UNIQUE(namespace, key)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # foreign_keys is per-connection in SQLite — must be set every time.
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _make_key(record: MemoryRecord) -> str:
        """broker:<scope>:<record_id>"""
        return f"broker:{record.scope.value}:{record.id}"

    @staticmethod
    def _make_tags(record: MemoryRecord) -> str:
        """JSON array of tags for Ruflo compatibility."""
        tags = ["broker", f"scope:{record.scope.value}"]
        if record.subject:
            tags.append(f"subject:{record.subject}")
        if record.workspace_id:
            tags.append(f"workspace:{record.workspace_id}")
        if record.user_id:
            tags.append(f"user:{record.user_id}")
        return json.dumps(tags)

    @staticmethod
    def _now_ms() -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    # -- public interface (matches broker adapter contract) -----------------

    def upsert(self, record: MemoryRecord) -> dict[str, Any]:
        """Insert or update a memory record into Ruflo's memory_entries table."""
        key = self._make_key(record)
        namespace = record.scope.value
        content = json.dumps(record.to_dict(), ensure_ascii=False)
        ruflo_type = _RUFLO_TYPE_MAP.get(record.scope.value, "semantic")
        tags = self._make_tags(record)
        metadata = json.dumps({
            "broker_event_id": record.event_id,
            "memory_type": record.memory_type.value,
            "confidence": record.confidence,
            "importance": record.importance,
            "provenance": record.provenance.to_dict(),
        }, ensure_ascii=False)
        now = self._now_ms()

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO memory_entries
                    (id, key, namespace, content, type, tags, metadata,
                     owner_id, created_at, updated_at, access_count, status)
                VALUES
                    (:id, :key, :ns, :content, :type, :tags, :meta,
                     :owner, :now, :now, 0, 'active')
                ON CONFLICT(namespace, key) DO UPDATE SET
                    content    = excluded.content,
                    tags       = excluded.tags,
                    metadata   = excluded.metadata,
                    updated_at = excluded.updated_at
                """,
                {
                    "id": record.id,
                    "key": key,
                    "ns": namespace,
                    "content": content,
                    "type": ruflo_type,
                    "tags": tags,
                    "meta": metadata,
                    "owner": record.user_id or "broker",
                    "now": now,
                },
            )
            conn.commit()
            log.info(
                "[ruflo] UPSERT scope=%s key=%s id=%s",
                namespace, key, record.id,
            )
            return {"backend": self.name, "status": "OK", "record_id": record.id, "key": key}
        except sqlite3.Error as exc:
            log.error("[ruflo] UPSERT FAILED id=%s: %s", record.id, exc)
            return {"backend": self.name, "status": "ERROR", "error": str(exc)}
        finally:
            conn.close()

    def retrieve(
        self,
        scope: MemoryScope | str,
        user_id: str,
        workspace_id: str,
        limit: int = 10,
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Retrieve broker-written records from memory_entries, filtered by scope.

        Returns parsed MemoryRecord dicts sorted by importance desc, then updated_at desc.
        Filtering by user_id, workspace_id, and optional query is done at the SQL level.
        """
        namespace = scope.value if isinstance(scope, MemoryScope) else scope

        conn = self._connect()
        try:
            # Build WHERE clause dynamically based on provided filters.
            clauses = [
                "namespace = :ns",
                "status = 'active'",
                "key LIKE 'broker:%'",
            ]
            params: dict[str, Any] = {"ns": namespace, "lim": limit}

            if user_id:
                clauses.append("owner_id = :owner_id")
                params["owner_id"] = user_id

            if workspace_id:
                clauses.append("tags LIKE :ws_pattern")
                params["ws_pattern"] = f'%"workspace:{workspace_id}"%'

            if query:
                # Split query into words; each word must appear in the content.
                # LIKE wildcards in user input are escaped to prevent abuse.
                for i, word in enumerate(query.split()):
                    if word:
                        param_key = f"qw{i}"
                        clauses.append(f"content LIKE :{param_key} ESCAPE '\\'")
                        params[param_key] = f"%{_escape_like(word)}%"

            where = " AND ".join(clauses)
            sql = f"""
                SELECT id, key, content, metadata, updated_at, access_count
                FROM memory_entries
                WHERE {where}
                ORDER BY
                    json_extract(metadata, '$.importance') DESC,
                    updated_at DESC
                LIMIT :lim
            """

            rows = conn.execute(sql, params).fetchall()

            results: list[dict[str, Any]] = []
            row_ids: list[str] = []
            for row in rows:
                try:
                    record_dict = json.loads(row["content"])
                except (json.JSONDecodeError, TypeError):
                    continue
                results.append(record_dict)
                row_ids.append(row["id"])

            # Batch-update access tracking for all returned rows in one statement.
            if row_ids:
                placeholders = ",".join("?" for _ in row_ids)
                now = self._now_ms()
                conn.execute(
                    f"""
                    UPDATE memory_entries
                    SET last_accessed_at = ?, access_count = access_count + 1
                    WHERE id IN ({placeholders})
                    """,
                    [now] + row_ids,
                )

            conn.commit()
            log.info(
                "[ruflo] RETRIEVE scope=%s user=%s workspace=%s -> %d records",
                namespace, user_id, workspace_id, len(results),
            )
            return results

        except sqlite3.Error as exc:
            log.error("[ruflo] RETRIEVE FAILED scope=%s: %s", namespace, exc)
            return []
        finally:
            conn.close()
