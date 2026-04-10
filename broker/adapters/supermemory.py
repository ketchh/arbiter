"""Supermemory adapter — canonical long-term memory backend.

Uses the Supermemory REST API (v3) via urllib (no extra dependencies).
All writes and reads go through the broker policy layer.

Endpoints used:
  POST /v3/documents       — add/update a memory document
  POST /v3/search          — search memories by query + container tags
  GET  /v3/documents/{id}  — retrieve a specific document by ID

Auth: Bearer token via SUPERMEMORY_API_KEY env var.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from broker.schema import MemoryRecord, MemoryScope

log = logging.getLogger(__name__)

_BASE_URL = "https://api.supermemory.ai"


class SupermemoryBackend:
    """Canonical long-term memory backend via Supermemory REST API."""

    name = "supermemory"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or _BASE_URL).rstrip("/")
        self.extra = extra or {}
        self._connected = bool(api_key)
        if self._connected:
            log.info("[supermemory] initialized with API key (len=%d)", len(api_key))

    # -- internal helpers ---------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated JSON request to the Supermemory API."""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None

        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            log.error(
                "[supermemory] HTTP %s %s -> %d: %s",
                method, path, exc.code, body_text[:300],
            )
            return {"error": f"HTTP {exc.code}", "detail": body_text[:300]}
        except urllib.error.URLError as exc:
            log.error("[supermemory] URL error %s %s: %s", method, path, exc.reason)
            return {"error": "URL_ERROR", "detail": str(exc.reason)}
        except Exception as exc:
            log.error("[supermemory] unexpected error: %s", exc)
            return {"error": "UNEXPECTED", "detail": str(exc)}

    def _container_tag(self, record: MemoryRecord) -> str:
        """Build a container tag from scope + workspace for isolation."""
        parts = ["broker"]
        if record.workspace_id:
            parts.append(record.workspace_id)
        parts.append(record.scope.value)
        return "-".join(parts)

    def _container_tag_for_scope(
        self, scope: str, workspace_id: str
    ) -> str:
        parts = ["broker"]
        if workspace_id:
            parts.append(workspace_id)
        parts.append(scope)
        return "-".join(parts)

    # -- public interface (matches broker adapter contract) -----------------

    def upsert(self, record: MemoryRecord) -> dict[str, Any]:
        """Add or update a memory document in Supermemory."""
        if not self._connected:
            log.info("[supermemory] NO_KEY — skipping upsert id=%s", record.id)
            return {"backend": self.name, "status": "NO_KEY", "record_id": record.id}

        content = (
            f"[{record.scope.value}/{record.memory_type.value}] "
            f"{record.subject}\n\n{record.content}"
        )

        metadata = {
            "broker_id": record.id,
            "broker_event_id": record.event_id,
            "scope": record.scope.value,
            "memory_type": record.memory_type.value,
            "confidence": record.confidence,
            "importance": record.importance,
            "user_id": record.user_id,
            "workspace_id": record.workspace_id,
        }
        prov = record.provenance.to_dict()
        if prov:
            metadata["provenance"] = json.dumps(prov)

        body: dict[str, Any] = {
            "content": content,
            "containerTag": self._container_tag(record),
            "customId": record.id,
            "metadata": metadata,
        }

        result = self._request("POST", "/v3/documents", body)

        if "error" in result:
            log.error(
                "[supermemory] UPSERT FAILED id=%s: %s",
                record.id, result.get("detail", result.get("error")),
            )
            return {
                "backend": self.name,
                "status": "ERROR",
                "record_id": record.id,
                "error": result.get("error"),
            }

        doc_id = result.get("id", "")
        status = result.get("status", "unknown")
        log.info(
            "[supermemory] UPSERT OK scope=%s id=%s doc_id=%s status=%s",
            record.scope.value, record.id, doc_id, status,
        )
        return {
            "backend": self.name,
            "status": "OK",
            "record_id": record.id,
            "supermemory_id": doc_id,
            "supermemory_status": status,
        }

    def retrieve(
        self,
        scope: MemoryScope | str,
        user_id: str,
        workspace_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search Supermemory for broker-written records in a given scope."""
        if not self._connected:
            log.info("[supermemory] NO_KEY — skipping retrieve scope=%s", scope)
            return []

        scope_val = scope.value if isinstance(scope, MemoryScope) else scope
        container_tag = self._container_tag_for_scope(scope_val, workspace_id)

        body: dict[str, Any] = {
            "q": f"scope:{scope_val}",
            "containerTags": [container_tag],
        }

        # Add metadata filter for user_id if provided
        if user_id:
            body["filters"] = {
                "AND": [
                    {
                        "key": "user_id",
                        "value": user_id,
                        "filterType": "metadata",
                    }
                ]
            }

        result = self._request("POST", "/v3/search", body)

        if "error" in result:
            log.error(
                "[supermemory] SEARCH FAILED scope=%s: %s",
                scope_val, result.get("detail", result.get("error")),
            )
            return []

        # Parse search results — Supermemory may return results in various shapes
        # depending on API version: "results", "memories", or top-level list.
        raw_results = (
            result.get("results")
            or result.get("memories")
            or (result if isinstance(result, list) else [])
        )
        records: list[dict[str, Any]] = []

        for item in raw_results[:limit]:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata", {})
            # Content can be in different fields depending on response shape
            content = (
                item.get("content")
                or item.get("chunk")
                or item.get("text")
                or item.get("summary")
                or ""
            )
            records.append({
                "id": metadata.get("broker_id", item.get("id", item.get("customId", ""))),
                "event_id": metadata.get("broker_event_id", ""),
                "scope": metadata.get("scope", scope_val),
                "memory_type": metadata.get("memory_type", "fact"),
                "content": content,
                "confidence": metadata.get("confidence", 0.5),
                "importance": metadata.get("importance", 0.5),
                "user_id": metadata.get("user_id", user_id),
                "workspace_id": metadata.get("workspace_id", workspace_id),
                "supermemory_score": item.get("score", 0),
            })

        log.info(
            "[supermemory] SEARCH scope=%s container=%s -> %d results",
            scope_val, container_tag, len(records),
        )
        return records
