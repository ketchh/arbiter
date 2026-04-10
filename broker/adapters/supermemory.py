"""Supermemory adapter stub.

Logs where writes would go without making real API calls.
Will be replaced with actual Supermemory SDK calls when the
hosted or self-hosted backend is connected.
"""

from __future__ import annotations

import logging
from typing import Any

from broker.schema import MemoryRecord, MemoryScope

log = logging.getLogger(__name__)


class SupermemoryBackend:
    """Stub: canonical long-term memory backend."""

    name = "supermemory"

    def __init__(self, api_key: str = "", base_url: str = "", extra: dict[str, Any] | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.extra = extra or {}
        self._connected = bool(api_key)

    def upsert(self, record: MemoryRecord) -> dict[str, Any]:
        """Stub: log the write destination, return the record dict."""
        status = "STUB_WRITE"
        if not self._connected:
            status = "STUB_NO_KEY"
        log.info(
            "[supermemory] %s scope=%s subject=%s id=%s",
            status, record.scope.value, record.subject, record.id,
        )
        return {"backend": self.name, "status": status, "record_id": record.id}

    def retrieve(
        self,
        scope: MemoryScope | str,
        user_id: str,
        workspace_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Stub: return empty list with log."""
        log.info(
            "[supermemory] STUB_RETRIEVE scope=%s user=%s workspace=%s",
            scope if isinstance(scope, str) else scope.value,
            user_id, workspace_id,
        )
        return []
