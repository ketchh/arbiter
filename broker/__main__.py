"""CLI entry point: python -m broker dry-run

Demonstrates event normalization, write routing, and retrieval
without side effects.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from broker.config import load_config
from broker.engine import BrokerEngine


def _sample_raw_event() -> dict:
    """A sample client event used for the dry-run demo."""
    return {
        "scope": "project",
        "memory_type": "decision",
        "subject": "workspace:sir",
        "content": "Supermemory is the canonical durable memory backend.",
        "confidence": 0.95,
        "importance": 0.85,
        "source": "manual_bootstrap",
        "provenance": {
            "actor": "workspace_bootstrap",
            "file": "instructions.md",
        },
    }


def _dump(label: str, data: object) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def cmd_dry_run(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    config = load_config(workspace)
    engine = BrokerEngine(config)

    print(f"Broker MVP dry-run  (workspace: {workspace})")
    print(f"userId={config.user_id}  workspaceId={config.workspace_id}  "
          f"projectId={config.project_id}")

    # -- Step 1: show config summary --
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

    # -- Step 2: normalize a sample client event --
    raw = _sample_raw_event()
    _dump("Raw client event (before normalization)", raw)

    event = engine.normalize(raw, client_name="claude-code")
    _dump("Normalized BrokerEvent", event.to_dict())

    # -- Step 3: capture with dry_run=True to show routing --
    result = engine.capture_event(event, dry_run=True)
    _dump("Write policy decision", {
        "scope": result.decision.scope,
        "target_backends": result.decision.backends,
        "reason": result.decision.reason,
        "explanation": result.decision.explain(),
    })
    _dump("Backend results (dry-run)", result.backend_results)

    # -- Step 4: capture for real to local cache --
    real_result = engine.capture_event(event, dry_run=False)
    _dump("Backend results (real write to local cache)", real_result.backend_results)

    # -- Step 5: retrieve from local cache --
    retrieval = engine.retrieve_context(
        query="canonical memory backend",
        scope_filters=["project"],
    )
    _dump("Retrieval results (scope=project)", [
        {"scope": r.scope, "backend": r.backend_source, "count": len(r.records),
         "records": r.records}
        for r in retrieval
    ])

    # -- Step 6: explain retrieval --
    explanation = engine.explain_retrieval(
        query="canonical memory backend",
        scope_filters=["project", "governance"],
    )
    _dump("Retrieval explanation", explanation)

    # -- Step 7: low-importance episodic event (policy filter demo) --
    low_event = engine.normalize(
        {
            "scope": "episodic",
            "memory_type": "episode",
            "subject": "debug:test",
            "content": "Ran a quick test, nothing notable.",
            "confidence": 0.3,
            "importance": 0.2,
        },
        client_name="claude-code",
    )
    low_result = engine.capture_event(low_event, dry_run=True)
    _dump("Low-importance episodic event (policy filter demo)", {
        "explanation": low_result.decision.explain(),
        "backends": low_result.decision.backends,
    })

    print(f"\n{'='*60}")
    print("  Dry-run complete. No external services were contacted.")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="broker",
        description="Memory broker MVP — client-neutral memory policy layer",
    )
    sub = parser.add_subparsers(dest="command")

    dry = sub.add_parser("dry-run", help="Run a full demo without side effects")
    dry.add_argument(
        "--workspace", "-w",
        default=".",
        help="Path to the workspace root (default: current directory)",
    )

    srv = sub.add_parser("serve", help="Start the broker HTTP server")
    srv.add_argument("--host", default="", help="Bind host (default: from config)")
    srv.add_argument("--port", type=int, default=0, help="Bind port (default: from config)")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "dry-run":
        cmd_dry_run(args)
    elif args.command == "serve":
        from broker.server import serve
        serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
