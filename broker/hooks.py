"""Ruflo hook bridge — auto-captures Ruflo hook events into the broker.

This module provides functions that translate Ruflo hook payloads
(post-task, post-edit, session-start, session-end) into broker events,
and sends them to the broker HTTP server or directly to the engine.

Usage as CLI (called by Ruflo hooks):
    python -m broker.hooks post-task --task-id X --task "description" --success
    python -m broker.hooks post-edit --file path/to/file --success

Usage as library:
    from broker.hooks import capture_post_task, capture_post_edit
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_BROKER_URL = "http://127.0.0.1:8081"


def _post_to_broker(
    broker_url: str,
    endpoint: str,
    payload: dict[str, Any],
    api_key: str = "",
) -> dict[str, Any]:
    """POST JSON to the broker HTTP server."""
    url = f"{broker_url.rstrip('/')}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        log.error("Broker %s returned %d: %s", endpoint, exc.code, body)
        return {"error": f"HTTP {exc.code}", "detail": body}
    except urllib.error.URLError as exc:
        log.warning("Broker unreachable at %s: %s", url, exc.reason)
        return {"error": "UNREACHABLE", "detail": str(exc.reason)}


def capture_post_task(
    task_id: str,
    task_description: str = "",
    success: bool = True,
    quality: float = 0.5,
    agent: str = "claude-code",
    broker_url: str = _DEFAULT_BROKER_URL,
    api_key: str = "",
) -> dict[str, Any]:
    """Capture a completed task as a procedural memory event."""
    importance = min(1.0, quality * 0.8 + (0.2 if success else 0.0))
    payload = {
        "client": agent,
        "scope": "procedural",
        "memory_type": "workflow",
        "subject": f"task:{task_id}",
        "content": (
            f"Task '{task_id}' {'completed successfully' if success else 'failed'}. "
            f"{task_description}"
        ),
        "confidence": quality,
        "importance": importance,
        "provenance": {
            "actor": agent,
            "session_id": task_id,
        },
    }
    return _post_to_broker(broker_url, "/capture", payload, api_key)


def capture_post_edit(
    file_path: str,
    success: bool = True,
    agent: str = "claude-code",
    broker_url: str = _DEFAULT_BROKER_URL,
    api_key: str = "",
) -> dict[str, Any]:
    """Capture a file edit as an episodic memory event."""
    payload = {
        "client": agent,
        "scope": "episodic",
        "memory_type": "episode",
        "subject": f"edit:{file_path}",
        "content": f"File '{file_path}' {'edited successfully' if success else 'edit failed'}.",
        "confidence": 0.9 if success else 0.4,
        "importance": 0.3,
        "provenance": {
            "actor": agent,
            "file": file_path,
        },
    }
    return _post_to_broker(broker_url, "/capture", payload, api_key)


def capture_session_event(
    event_type: str,
    session_id: str = "",
    agent: str = "claude-code",
    broker_url: str = _DEFAULT_BROKER_URL,
    api_key: str = "",
) -> dict[str, Any]:
    """Capture a session start/end as an episodic memory event."""
    payload = {
        "client": agent,
        "scope": "episodic",
        "memory_type": "episode",
        "subject": f"session:{event_type}",
        "content": f"Session {event_type} for agent '{agent}'.",
        "confidence": 1.0,
        "importance": 0.4,
        "provenance": {
            "actor": agent,
            "session_id": session_id,
        },
    }
    return _post_to_broker(broker_url, "/capture", payload, api_key)


def main() -> None:
    """CLI entry point for Ruflo hook integration."""
    parser = argparse.ArgumentParser(
        prog="broker.hooks",
        description="Bridge between Ruflo hooks and the memory broker",
    )
    parser.add_argument("--broker-url", default=_DEFAULT_BROKER_URL)
    parser.add_argument("--api-key", default="")

    sub = parser.add_subparsers(dest="command")

    pt = sub.add_parser("post-task", help="Capture a completed task")
    pt.add_argument("--task-id", required=True)
    pt.add_argument("--task", default="")
    pt.add_argument("--success", action="store_true", default=True)
    pt.add_argument("--failed", action="store_true")
    pt.add_argument("--quality", type=float, default=0.5)
    pt.add_argument("--agent", default="claude-code")

    pe = sub.add_parser("post-edit", help="Capture a file edit")
    pe.add_argument("--file", required=True)
    pe.add_argument("--success", action="store_true", default=True)
    pe.add_argument("--failed", action="store_true")
    pe.add_argument("--agent", default="claude-code")

    ss = sub.add_parser("session", help="Capture a session event")
    ss.add_argument("--type", choices=["start", "end"], required=True)
    ss.add_argument("--session-id", default="")
    ss.add_argument("--agent", default="claude-code")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.command == "post-task":
        result = capture_post_task(
            task_id=args.task_id,
            task_description=args.task,
            success=not args.failed,
            quality=args.quality,
            agent=args.agent,
            broker_url=args.broker_url,
            api_key=args.api_key,
        )
    elif args.command == "post-edit":
        result = capture_post_edit(
            file_path=args.file,
            success=not args.failed,
            agent=args.agent,
            broker_url=args.broker_url,
            api_key=args.api_key,
        )
    elif args.command == "session":
        result = capture_session_event(
            event_type=args.type,
            session_id=args.session_id,
            agent=args.agent,
            broker_url=args.broker_url,
            api_key=args.api_key,
        )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
