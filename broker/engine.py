"""Broker engine — capture, upsert, retrieve, explain."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from broker.config import BrokerConfig, load_config
from broker.schema import (
    BrokerEvent,
    MemoryRecord,
    MemoryScope,
    normalize_client_event,
)
from broker.policy import WriteDecision, evaluate_write
from broker.adapters.local_cache import LocalCacheBackend
from broker.adapters.supermemory import SupermemoryBackend
from broker.adapters.ruflo import RufloBackend

log = logging.getLogger(__name__)


@dataclass
class WriteResult:
    event: BrokerEvent
    record: MemoryRecord
    decision: WriteDecision
    backend_results: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    scope: str
    backend_source: str
    records: list[dict[str, Any]]


class BrokerEngine:
    """Core broker: wires config, policy, and adapters together."""

    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or load_config()
        self._backends: dict[str, Any] = {}
        self._init_backends()

    def _init_backends(self) -> None:
        cfg = self.config

        if cfg.local_cache.enabled:
            self._backends["local_cache"] = LocalCacheBackend(cfg.local_cache_path)

        if cfg.supermemory.enabled:
            self._backends["supermemory"] = SupermemoryBackend(
                api_key=os.environ.get("SUPERMEMORY_API_KEY", ""),
                base_url=os.environ.get("SUPERMEMORY_BASE_URL", ""),
                extra=cfg.supermemory.extra,
            )

        if cfg.ruflo.enabled:
            self._backends["ruflo"] = RufloBackend(
                data_path=os.environ.get(
                    "RUFLO_DB_PATH", ".swarm/memory.db"
                ),
                extra=cfg.ruflo.extra,
            )

    # -- Public interface matching docs/memory-broker.md --

    def normalize(self, raw_event: dict[str, Any], client_name: str = "") -> BrokerEvent:
        """Normalize a raw client event into a BrokerEvent."""
        return normalize_client_event(
            raw_event,
            client_name=client_name or self.config.preferred_client,
            user_id=self.config.user_id,
            workspace_id=self.config.workspace_id,
        )

    def capture_event(self, event: BrokerEvent, dry_run: bool = False) -> WriteResult:
        """Evaluate policy and write to backends (or simulate in dry-run)."""
        record = MemoryRecord.from_event(event)
        decision = evaluate_write(event, self.config)

        backend_results: dict[str, Any] = {}
        for backend_name in decision.backends:
            backend = self._backends.get(backend_name)
            if backend is None:
                backend_results[backend_name] = {"status": "BACKEND_NOT_INITIALIZED"}
                continue
            if dry_run:
                backend_results[backend_name] = {"status": "DRY_RUN", "would_write": True}
            else:
                backend_results[backend_name] = backend.upsert(record)

        return WriteResult(
            event=event,
            record=record,
            decision=decision,
            backend_results=backend_results,
        )

    def upsert_memory(self, record: MemoryRecord, dry_run: bool = False) -> dict[str, Any]:
        """Direct upsert of a MemoryRecord to policy-selected backends."""
        # Build a minimal event to evaluate policy
        event = BrokerEvent(
            scope=record.scope,
            importance=record.importance,
        )
        decision = evaluate_write(event, self.config)
        results: dict[str, Any] = {}
        for backend_name in decision.backends:
            backend = self._backends.get(backend_name)
            if backend is None:
                continue
            if dry_run:
                results[backend_name] = {"status": "DRY_RUN"}
            else:
                results[backend_name] = backend.upsert(record)
        return results

    def retrieve_context(
        self,
        query: str,
        scope_filters: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve context from backends, merged by scope."""
        scopes = scope_filters or [s.value for s in MemoryScope]
        results: list[RetrievalResult] = []

        for scope in scopes:
            limit = self.config.retrieval_limits.get(scope, 10)
            for backend_name, backend in self._backends.items():
                records = backend.retrieve(
                    scope=scope,
                    user_id=self.config.user_id,
                    workspace_id=self.config.workspace_id,
                    limit=limit,
                )
                if records:
                    results.append(RetrievalResult(
                        scope=scope,
                        backend_source=backend_name,
                        records=records,
                    ))

        return results

    def explain_retrieval(
        self,
        query: str,
        scope_filters: list[str] | None = None,
    ) -> dict[str, Any]:
        """Explain what retrieval would do without fetching."""
        scopes = scope_filters or [s.value for s in MemoryScope]
        explanation: dict[str, Any] = {
            "query": query,
            "user_id": self.config.user_id,
            "workspace_id": self.config.workspace_id,
            "scopes_queried": scopes,
            "backends_consulted": [],
            "limits": {},
        }
        for scope in scopes:
            explanation["limits"][scope] = self.config.retrieval_limits.get(scope, 10)

        for name in self._backends:
            explanation["backends_consulted"].append(name)

        return explanation

    def flush_local_cache(self) -> int:
        """Flush the local cache backend. Returns count of files removed."""
        backend = self._backends.get("local_cache")
        if isinstance(backend, LocalCacheBackend):
            return backend.flush()
        return 0
