"""Config loader: reads .env then merges broker JSON config."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_dotenv(env_path: Path) -> None:
    """Minimal .env loader — no external dependency needed."""
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        # Only set if not already in environment (real env wins)
        if key not in os.environ:
            os.environ[key] = value


def _load_json_config(config_path: Path) -> dict[str, Any]:
    """Load broker JSON config, falling back to example if needed."""
    if config_path.is_file():
        return json.loads(config_path.read_text(encoding="utf-8"))
    # Fallback: try config.example.json in the same directory
    example = config_path.parent / "config.example.json"
    if example.is_file():
        return json.loads(example.read_text(encoding="utf-8"))
    return {}


@dataclass
class BackendConfig:
    enabled: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerConfig:
    project_id: str = "sir"
    user_id: str = "default-user"
    workspace_id: str = ""

    canonical_memory: str = "supermemory"
    preferred_client: str = "claude-code"

    local_cache_path: str = "./.broker/cache"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8081

    supermemory: BackendConfig = field(default_factory=lambda: BackendConfig(enabled=True))
    ruflo: BackendConfig = field(default_factory=lambda: BackendConfig(enabled=True))
    local_cache: BackendConfig = field(default_factory=lambda: BackendConfig(enabled=True))

    # Write policy: scope -> list of backends that receive writes
    write_policy: dict[str, list[str]] = field(default_factory=dict)

    # Retrieval limits per scope
    retrieval_limits: dict[str, int] = field(default_factory=dict)

    # Raw JSON for anything adapters need
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(
    workspace_root: Path | None = None,
) -> BrokerConfig:
    """Load config from .env + JSON, with env-var overrides."""
    if workspace_root is None:
        workspace_root = Path.cwd()

    # 1. Load .env (sets os.environ for vars not already present)
    _load_dotenv(workspace_root / ".env")

    # 2. Load JSON config
    config_path = Path(
        os.environ.get("BROKER_CONFIG_PATH", "broker/config.json")
    )
    if not config_path.is_absolute():
        config_path = workspace_root / config_path
    raw = _load_json_config(config_path)

    # 3. Build BrokerConfig — env vars override JSON values
    cfg = BrokerConfig()
    cfg.raw = raw

    cfg.project_id = os.environ.get(
        "BROKER_PROJECT_ID", raw.get("projectId", cfg.project_id)
    )
    cfg.user_id = os.environ.get(
        "BROKER_USER_ID", raw.get("userId", cfg.user_id)
    )
    # workspaceId defaults to projectId if not set separately
    cfg.workspace_id = os.environ.get(
        "BROKER_WORKSPACE_ID", raw.get("workspaceId", cfg.project_id)
    )

    cfg.canonical_memory = os.environ.get(
        "BROKER_CANONICAL_MEMORY",
        raw.get("canonicalMemory", cfg.canonical_memory),
    )
    runtime = raw.get("runtime", {})
    cfg.preferred_client = os.environ.get(
        "BROKER_CLIENT_ADAPTER",
        runtime.get("preferredClient", cfg.preferred_client),
    )

    cfg.local_cache_path = os.environ.get(
        "BROKER_LOCAL_CACHE_PATH",
        raw.get("backends", {}).get("localCache", {}).get("path", cfg.local_cache_path),
    )
    cfg.bind_host = os.environ.get("BROKER_BIND_HOST", cfg.bind_host)
    cfg.bind_port = int(os.environ.get("BROKER_BIND_PORT", str(cfg.bind_port)))

    # Backend toggles
    backends = raw.get("backends", {})
    for name, attr in [("supermemory", "supermemory"), ("ruflo", "ruflo"), ("localCache", "local_cache")]:
        section = backends.get(name, {})
        bc = BackendConfig(
            enabled=section.get("enabled", True),
            extra={k: v for k, v in section.items() if k != "enabled"},
        )
        setattr(cfg, attr, bc)

    # Write policy from JSON policies.writeThroughScopes + docs/memory-broker.md table
    _build_write_policy(cfg, raw)

    # Retrieval limits
    retrieval = raw.get("retrieval", {})
    cfg.retrieval_limits = {
        "profile": retrieval.get("maxProfileMemories", 8),
        "project": retrieval.get("maxProjectMemories", 12),
        "episodic": retrieval.get("maxEpisodicMemories", 10),
        "procedural": retrieval.get("maxProceduralMemories", 10),
        "governance": retrieval.get("maxGovernanceMemories", 5),
    }

    return cfg


def _build_write_policy(cfg: BrokerConfig, raw: dict[str, Any]) -> None:
    """Build scope -> backend write routing from the documented policy table."""
    # Default policy mirrors docs/memory-broker.md "Recommended Write Policy"
    default_policy: dict[str, list[str]] = {
        "profile":     ["supermemory", "local_cache"],
        "project":     ["supermemory", "ruflo", "local_cache"],
        "episodic":    ["supermemory", "ruflo", "local_cache"],
        "procedural":  ["supermemory", "ruflo", "local_cache"],
        "governance":  ["supermemory", "local_cache"],
    }
    cfg.write_policy = default_policy

    # Filter out disabled backends
    enabled = set()
    if cfg.supermemory.enabled:
        enabled.add("supermemory")
    if cfg.ruflo.enabled:
        enabled.add("ruflo")
    if cfg.local_cache.enabled:
        enabled.add("local_cache")

    for scope in cfg.write_policy:
        cfg.write_policy[scope] = [b for b in cfg.write_policy[scope] if b in enabled]
