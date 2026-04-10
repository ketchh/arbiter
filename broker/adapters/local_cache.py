"""Local JSON file cache — canonical temporary backend.

Stores memory records as one JSON file per scope under the configured
cache directory. It coexists with the Ruflo sqlite adapter and the
Supermemory REST adapter in the broker's multi-backend architecture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from broker.schema import MemoryRecord, MemoryScope


class LocalCacheBackend:
    """Flat-file JSON backend: one file per scope."""

    name = "local_cache"

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    _VALID_SCOPES = {"profile", "project", "episodic", "procedural", "governance"}

    def _scope_path(self, scope: MemoryScope | str) -> Path:
        scope_val = scope.value if isinstance(scope, MemoryScope) else scope
        if scope_val not in self._VALID_SCOPES:
            raise ValueError(f"Invalid scope: {scope_val!r}")
        return self.cache_dir / f"{scope_val}.json"

    def _read_scope(self, scope: MemoryScope | str) -> list[dict[str, Any]]:
        path = self._scope_path(scope)
        if not path.is_file():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_scope(self, scope: MemoryScope | str, records: list[dict[str, Any]]) -> None:
        path = self._scope_path(scope)
        path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def upsert(self, record: MemoryRecord) -> dict[str, Any]:
        """Insert or update a memory record. Returns the stored dict."""
        records = self._read_scope(record.scope)
        # Update if same id exists
        for i, r in enumerate(records):
            if r.get("id") == record.id:
                records[i] = record.to_dict()
                self._write_scope(record.scope, records)
                return records[i]
        # Insert
        records.append(record.to_dict())
        self._write_scope(record.scope, records)
        return record.to_dict()

    def retrieve(
        self,
        scope: MemoryScope | str,
        user_id: str,
        workspace_id: str,
        limit: int = 10,
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Retrieve records for a given scope, filtered by user+workspace.

        When *query* is provided, only records whose ``content`` or ``subject``
        contain the query string (case-insensitive) are returned.
        """
        records = self._read_scope(scope)
        matched = [
            r for r in records
            if r.get("user_id") == user_id
            and r.get("workspace_id") == workspace_id
        ]

        # Optional text-search filter
        if query:
            q_lower = query.lower()
            matched = [
                r for r in matched
                if q_lower in str(r.get("content", "")).lower()
                or q_lower in str(r.get("subject", "")).lower()
            ]

        # Sort by importance descending, then by created_at descending
        matched.sort(
            key=lambda r: (r.get("importance", 0), r.get("created_at", "")),
            reverse=True,
        )
        return matched[:limit]

    def flush(self) -> int:
        """Delete all cached files. Returns count of files removed."""
        count = 0
        for path in self.cache_dir.glob("*.json"):
            path.unlink()
            count += 1
        return count
