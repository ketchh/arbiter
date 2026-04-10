"""CLI entry point: arbiter <command>

Commands:
  serve      Start the broker HTTP server
  dry-run    Demo event normalization and write routing
  capture    Send a memory event to the running server
  retrieve   Retrieve context from the running server
  status     Show broker config and backend status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

from broker.config import load_config
from broker.engine import BrokerEngine

log = logging.getLogger(__name__)


def _dump(label: str, data: object) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _http_post(url: str, body: dict, api_key: str = "") -> dict:
    """POST JSON and return response dict."""
    data = json.dumps(body).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}", "detail": exc.read().decode()[:300]}
    except urllib.error.URLError as exc:
        return {"error": "UNREACHABLE", "detail": str(exc.reason)}


def _http_get(url: str, api_key: str = "") -> dict:
    """GET and return response dict."""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}", "detail": exc.read().decode()[:300]}
    except urllib.error.URLError as exc:
        return {"error": "UNREACHABLE", "detail": str(exc.reason)}


# -- Commands ---------------------------------------------------------------

def cmd_serve(args: argparse.Namespace) -> None:
    from broker.server import serve
    serve(host=args.host, port=args.port)


def cmd_dry_run(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    config = load_config(workspace)
    engine = BrokerEngine(config)

    print(f"Broker dry-run  (workspace: {workspace})")
    print(f"userId={config.user_id}  workspaceId={config.workspace_id}  "
          f"projectId={config.project_id}")

    _dump("Config summary", {
        "canonical_memory": config.canonical_memory,
        "preferred_client": config.preferred_client,
        "backends": {
            "supermemory": {"enabled": config.supermemory.enabled},
            "ruflo": {"enabled": config.ruflo.enabled},
            "local_cache": {"enabled": config.local_cache.enabled,
                            "path": config.local_cache_path},
        },
        "write_policy": config.write_policy,
        "retrieval_limits": config.retrieval_limits,
    })

    raw = {
        "scope": "project",
        "memory_type": "decision",
        "subject": "workspace:sir",
        "content": "Supermemory is the canonical durable memory backend.",
        "confidence": 0.95,
        "importance": 0.85,
        "source": "manual_bootstrap",
        "provenance": {"actor": "workspace_bootstrap", "file": "instructions.md"},
    }
    event = engine.normalize(raw, client_name="claude-code")
    _dump("Normalized BrokerEvent", event.to_dict())

    result = engine.capture_event(event, dry_run=True)
    _dump("Write policy decision", {
        "scope": result.decision.scope,
        "target_backends": result.decision.backends,
        "reason": result.decision.reason,
    })
    _dump("Backend results (dry-run)", result.backend_results)

    print(f"\n{'='*60}")
    print("  Dry-run complete.")
    print(f"{'='*60}\n")


def cmd_capture(args: argparse.Namespace) -> None:
    base = args.url.rstrip("/")
    body: dict = {
        "client": args.client,
        "scope": args.scope,
        "memory_type": args.type,
        "subject": args.subject,
        "content": args.content,
        "confidence": args.confidence,
        "importance": args.importance,
    }
    if args.dry_run:
        body["dry_run"] = True

    result = _http_post(f"{base}/capture", body, api_key=args.api_key)
    print(json.dumps(result, indent=2, default=str))


def cmd_retrieve(args: argparse.Namespace) -> None:
    base = args.url.rstrip("/")
    body: dict = {"query": args.query}
    if args.scopes:
        body["scope_filters"] = args.scopes.split(",")

    result = _http_post(f"{base}/retrieve", body, api_key=args.api_key)
    print(json.dumps(result, indent=2, default=str))


def cmd_status(args: argparse.Namespace) -> None:
    base = args.url.rstrip("/")

    health = _http_get(f"{base}/health")
    if "error" in health:
        print(f"Broker unreachable at {base}")
        print(json.dumps(health, indent=2))
        sys.exit(1)

    print(f"Broker: {base}")
    print(f"  status:     {health.get('status', '?')}")
    print(f"  project_id: {health.get('project_id', '?')}")
    print(f"  backends:   {', '.join(health.get('backends', []))}")

    metrics = _http_get(f"{base}/metrics", api_key=args.api_key)
    if "error" not in metrics:
        print(f"  uptime:     {metrics.get('uptime_seconds', '?')}s")
        print(f"  requests:   {metrics.get('total_requests', '?')}")
        print(f"  rate_limited: {metrics.get('rate_limited', '?')}")
        by_path = metrics.get("by_path", {})
        if by_path:
            print(f"  by_path:    {json.dumps(by_path)}")


# -- Main -------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arbiter",
        description="Arbiter — runtime-agnostic memory broker for AI clients",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    srv = sub.add_parser("serve", help="Start the broker HTTP server")
    srv.add_argument("--host", default="", help="Bind host (default: from config)")
    srv.add_argument("--port", type=int, default=0, help="Bind port (default: from config)")

    # dry-run
    dry = sub.add_parser("dry-run", help="Demo event normalization and routing")
    dry.add_argument("--workspace", "-w", default=".", help="Workspace root")

    # capture
    cap = sub.add_parser("capture", help="Send a memory event to the broker")
    cap.add_argument("content", help="Memory content text")
    cap.add_argument("--scope", "-s", default="episodic",
                     choices=["profile", "project", "episodic", "procedural", "governance"])
    cap.add_argument("--type", "-t", default="fact",
                     choices=["decision", "fact", "preference", "convention", "episode", "workflow", "rule"])
    cap.add_argument("--subject", default="")
    cap.add_argument("--client", default="cli")
    cap.add_argument("--confidence", type=float, default=0.8)
    cap.add_argument("--importance", type=float, default=0.5)
    cap.add_argument("--dry-run", action="store_true")
    cap.add_argument("--url", default="http://127.0.0.1:8081", help="Broker URL")
    cap.add_argument("--api-key", default="", help="Bearer token")

    # retrieve
    ret = sub.add_parser("retrieve", help="Retrieve context from the broker")
    ret.add_argument("query", help="Search query")
    ret.add_argument("--scopes", default="", help="Comma-separated scopes (e.g. project,episodic)")
    ret.add_argument("--url", default="http://127.0.0.1:8081", help="Broker URL")
    ret.add_argument("--api-key", default="", help="Bearer token")

    # status
    st = sub.add_parser("status", help="Show broker status and metrics")
    st.add_argument("--url", default="http://127.0.0.1:8081", help="Broker URL")
    st.add_argument("--api-key", default="", help="Bearer token")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cmds = {
        "serve": cmd_serve,
        "dry-run": cmd_dry_run,
        "capture": cmd_capture,
        "retrieve": cmd_retrieve,
        "status": cmd_status,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
