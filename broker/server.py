"""Minimal HTTP server for the memory broker.

Exposes the broker engine over HTTP so any client can POST events
and GET context without importing the broker package directly.

Endpoints:
  POST /capture        — normalize + capture a client event
  POST /retrieve       — retrieve context by scope
  POST /explain        — explain what retrieval would do
  POST /upsert         — direct upsert of a memory record
  DELETE /cache         — flush the local cache
  GET  /health         — liveness check

Default bind: 127.0.0.1:8081 (configurable via BROKER_BIND_HOST/PORT).
"""

from __future__ import annotations

import json
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from broker.config import load_config
from broker.engine import BrokerEngine

log = logging.getLogger(__name__)


def _json_response(handler: "BrokerHandler", status: int, body: Any) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(
        json.dumps(body, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    )


def _read_json_body(handler: "BrokerHandler") -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


class BrokerHandler(BaseHTTPRequestHandler):
    """Request handler — routes to BrokerEngine methods."""

    engine: BrokerEngine  # set on the class before serving

    def log_message(self, format: str, *args: Any) -> None:
        log.info(format, *args)

    # -- CORS preflight ---------------------------------------------------

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # -- GET routes -------------------------------------------------------

    def do_GET(self) -> None:
        if self.path == "/health":
            _json_response(self, 200, {
                "status": "ok",
                "project_id": self.engine.config.project_id,
                "backends": list(self.engine._backends.keys()),
            })
        else:
            _json_response(self, 404, {"error": "not found"})

    # -- POST routes ------------------------------------------------------

    def do_POST(self) -> None:
        try:
            body = _read_json_body(self)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            _json_response(self, 400, {"error": "invalid JSON", "detail": str(exc)})
            return

        if self.path == "/capture":
            self._handle_capture(body)
        elif self.path == "/retrieve":
            self._handle_retrieve(body)
        elif self.path == "/explain":
            self._handle_explain(body)
        elif self.path == "/upsert":
            self._handle_upsert(body)
        else:
            _json_response(self, 404, {"error": "not found"})

    # -- DELETE routes ----------------------------------------------------

    def do_DELETE(self) -> None:
        if self.path == "/cache":
            count = self.engine.flush_local_cache()
            _json_response(self, 200, {"flushed": count})
        else:
            _json_response(self, 404, {"error": "not found"})

    # -- handler implementations ------------------------------------------

    def _handle_capture(self, body: dict[str, Any]) -> None:
        client = body.pop("client", "")
        dry_run = body.pop("dry_run", False)

        event = self.engine.normalize(body, client_name=client)
        result = self.engine.capture_event(event, dry_run=dry_run)

        _json_response(self, 200, {
            "event_id": result.event.id,
            "record_id": result.record.id,
            "decision": {
                "scope": result.decision.scope,
                "backends": result.decision.backends,
                "reason": result.decision.reason,
            },
            "backend_results": result.backend_results,
        })

    def _handle_retrieve(self, body: dict[str, Any]) -> None:
        query = body.get("query", body.get("q", ""))
        scope_filters = body.get("scope_filters", body.get("scopes"))

        results = self.engine.retrieve_context(
            query=query,
            scope_filters=scope_filters,
        )

        _json_response(self, 200, {
            "results": [
                {
                    "scope": r.scope,
                    "backend": r.backend_source,
                    "count": len(r.records),
                    "records": r.records,
                }
                for r in results
            ],
        })

    def _handle_explain(self, body: dict[str, Any]) -> None:
        query = body.get("query", body.get("q", ""))
        scope_filters = body.get("scope_filters", body.get("scopes"))

        explanation = self.engine.explain_retrieval(
            query=query,
            scope_filters=scope_filters,
        )
        _json_response(self, 200, explanation)

    def _handle_upsert(self, body: dict[str, Any]) -> None:
        from broker.schema import MemoryRecord, MemoryScope, MemoryType, Provenance

        record = MemoryRecord(
            id=body.get("id", ""),
            event_id=body.get("event_id", ""),
            user_id=body.get("user_id", ""),
            workspace_id=body.get("workspace_id", ""),
            scope=MemoryScope(body.get("scope", "episodic")),
            memory_type=MemoryType(body.get("memory_type", "fact")),
            subject=body.get("subject", ""),
            content=body.get("content", ""),
            confidence=body.get("confidence", 0.5),
            importance=body.get("importance", 0.5),
            provenance=Provenance(
                actor=body.get("provenance", {}).get("actor", ""),
                file=body.get("provenance", {}).get("file", ""),
                session_id=body.get("provenance", {}).get("session_id", ""),
            ),
        )

        dry_run = body.get("dry_run", False)
        results = self.engine.upsert_memory(record, dry_run=dry_run)

        _json_response(self, 200, {
            "record_id": record.id,
            "backend_results": results,
        })


def serve(host: str = "", port: int = 0) -> None:
    """Start the broker HTTP server."""
    config = load_config()
    engine = BrokerEngine(config)

    host = host or config.bind_host
    port = port or config.bind_port

    BrokerHandler.engine = engine

    server = HTTPServer((host, port), BrokerHandler)
    log.info("Broker server listening on %s:%d", host, port)
    print(f"Broker server listening on http://{host}:{port}")
    print(f"  project={config.project_id}  backends={list(engine._backends.keys())}")
    print("  Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    serve()
