"""Minimal MCP resource provider that proxies to the broker HTTP API.

Provides three resource endpoints that can be used by MCP-compatible clients
to query the broker without importing the broker package directly.

Resources:
    broker://health          - broker health check
    broker://retrieve/{scope} - retrieve memories by scope
    broker://metrics         - request metrics

Usage as library:
    from broker.mcp_resources import get_health, retrieve_by_scope, get_metrics

Usage as CLI (for quick testing):
    python -m broker.mcp_resources health
    python -m broker.mcp_resources retrieve episodic
    python -m broker.mcp_resources retrieve project --query "architecture"
    python -m broker.mcp_resources metrics
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_BROKER_URL = os.environ.get("BROKER_URL", "http://127.0.0.1:8081")
_API_KEY = os.environ.get("BROKER_API_KEY", "")


def _request(
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    broker_url: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """Make an HTTP request to the broker server."""
    base = (broker_url or _DEFAULT_BROKER_URL).rstrip("/")
    url = f"{base}{endpoint}"

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = api_key or _API_KEY
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        log.error("Broker %s returned %d: %s", endpoint, exc.code, body)
        return {"error": f"HTTP {exc.code}", "detail": body}
    except urllib.error.URLError as exc:
        log.warning("Broker unreachable at %s: %s", url, exc.reason)
        return {"error": "UNREACHABLE", "detail": str(exc.reason)}


# ---------------------------------------------------------------------------
# Resource: broker://health
# ---------------------------------------------------------------------------

def get_health(broker_url: str = "", api_key: str = "") -> dict[str, Any]:
    """Check broker health status.

    Returns server status, project ID, and active backends.
    This endpoint does not require authentication.
    """
    return _request("GET", "/health", broker_url=broker_url, api_key=api_key)


# ---------------------------------------------------------------------------
# Resource: broker://retrieve/{scope}
# ---------------------------------------------------------------------------

def retrieve_by_scope(
    scope: str,
    query: str = "",
    broker_url: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    """Retrieve memories filtered by scope.

    Args:
        scope: One of profile, project, episodic, procedural, governance.
        query: Optional search query to filter results.
        broker_url: Override the default broker URL.
        api_key: Override the default API key.

    Returns:
        Dict with 'results' key containing scoped memory records.
    """
    payload: dict[str, Any] = {"scope_filters": [scope]}
    if query:
        payload["query"] = query
    return _request("POST", "/retrieve", payload=payload, broker_url=broker_url, api_key=api_key)


# ---------------------------------------------------------------------------
# Resource: broker://metrics
# ---------------------------------------------------------------------------

def get_metrics(broker_url: str = "", api_key: str = "") -> dict[str, Any]:
    """Fetch broker request metrics.

    Returns uptime, total requests, rate-limited count, and per-path/status breakdowns.
    Requires authentication when BROKER_API_KEY is set.
    """
    return _request("GET", "/metrics", broker_url=broker_url, api_key=api_key)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI for testing MCP resource proxies."""
    parser = argparse.ArgumentParser(
        prog="broker.mcp_resources",
        description="Query broker MCP resources",
    )
    parser.add_argument("--broker-url", default="")
    parser.add_argument("--api-key", default="")

    sub = parser.add_subparsers(dest="resource")

    sub.add_parser("health", help="Check broker health")

    ret = sub.add_parser("retrieve", help="Retrieve memories by scope")
    ret.add_argument("scope", choices=["profile", "project", "episodic", "procedural", "governance"])
    ret.add_argument("--query", "-q", default="", help="Optional search query")

    sub.add_parser("metrics", help="Get broker metrics")

    args = parser.parse_args()
    if args.resource is None:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.resource == "health":
        result = get_health(broker_url=args.broker_url, api_key=args.api_key)
    elif args.resource == "retrieve":
        result = retrieve_by_scope(
            scope=args.scope,
            query=args.query,
            broker_url=args.broker_url,
            api_key=args.api_key,
        )
    elif args.resource == "metrics":
        result = get_metrics(broker_url=args.broker_url, api_key=args.api_key)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
