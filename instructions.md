@docs/setup-minimo.md
@docs/memory-broker.md

# Continuation Instructions

_Last updated: 2026-04-10 (git init + GitHub push + GitHub Actions app installed). Read this file completely before touching anything._

---

## Snapshot: What Exists Right Now

### Workspace root (`C:\Users\aless\Documents\ancora non lo so\SIR\`)
```
CLAUDE.md                      ← workspace entrypoint for Claude Code
instructions.md                ← this file (imported by CLAUDE.md)
claude-flow.config.json        ← Ruflo project config
.env.example                   ← all env var placeholders (no secrets)
.gitignore                     ← includes .swarm/, .env, .broker/
broker/                        ← Python memory broker MVP
docs/                          ← architecture docs
.swarm/                        ← Ruflo runtime data (memory.db, schema.sql, tasks)
.claude-flow/                  ← Ruflo task store from swarm experiments
.broker/                       ← local cache backend files (one JSON per scope)
.claude/                       ← Claude Code project config
```

### Broker package (`broker/`)
| File | State | Notes |
|------|-------|-------|
| `__init__.py` | real | empty, marks package |
| `__main__.py` | real | CLI entry: `python -m broker dry-run` |
| `engine.py` | real | BrokerEngine, wires config+policy+adapters; default DB `.swarm/memory.db`; env var `RUFLO_DB_PATH` |
| `schema.py` | real | BrokerEvent, MemoryRecord, MemoryScope; `clamp_unit()` enforces [0,1] on confidence/importance; `normalize_client_event()` |
| `policy.py` | real | `evaluate_write()`, `WriteDecision`; routes by scope |
| `config.py` | real | BrokerConfig dataclass, `load_config()`, `_build_write_policy()` |
| `config.example.json` | complete | all 5 retrieval limits: maxProfile 1, maxProject 5, maxEpisodic 20, maxProcedural 10, maxGovernance 5 |
| `adapters/__init__.py` | real | |
| `adapters/ruflo.py` | **REAL** | sqlite3 adapter reading/writing `.swarm/memory.db`; key pattern `broker:<scope>:<record_id>`; namespace = scope value; ON CONFLICT DO UPDATE; access_count tracking |
| `adapters/local_cache.py` | **REAL** | flat-file JSON backend under `.broker/cache/`; one file per scope |
| `adapters/supermemory.py` | **STUB** | logs writes, returns empty — no real API calls yet |

### Documentation (`docs/`)
| File | Content |
|------|---------|
| `memory-broker.md` | full architecture + "Current Practical Role" section (updated) |
| `setup-minimo.md` | manual setup guide (updated) |
| `ruflo-swarm-report.md` | full trace of the 21-call swarm experiment |
| `topologia-server.md` | server topology |

---

## Integration State

### Ruflo MCP
- Version: 3.5.78
- MCP server config lives in `C:\Users\aless\.claude.json` (project-level, private/gitignored):
  ```json
  {
    "type": "stdio",
    "command": "cmd",
    "args": ["/c", "npx", "-y", "ruflo@latest", "mcp", "start"]
  }
  ```
- Exposes **170+ MCP tools** (not slash commands). Categories: Agent, Swarm, Memory, Config, Task, Session, Hive-mind, Workflow, Analyze, Embeddings, Claims, Transfer, Hooks, AgentDB, ruvllm, wasm, guidance.
- Ruflo agents are **coordination records**, not spawned processes — no visual window per agent.
- `.swarm/memory.db` is the shared sqlite DB between Ruflo MCP tools and the Python broker.

### Memory round-trip (proven)
A swarm with 2 agents (agent-reviewer, agent-planner) ran successfully:
- 21 MCP tool calls executed
- `swarm_memory_store` → `swarm_memory_search` → `swarm_memory_retrieve` all worked
- Broker write → Ruflo sqlite read confirmed via `broker/adapters/ruflo.py`

### Supermemory
- **Not connected yet.** Adapter at `broker/adapters/supermemory.py` is a stub.
- Canonical long-term memory target; waiting for API key in `SUPERMEMORY_API_KEY` env var.
- Do not bypass the broker layer when integrating — all writes must go through `engine.py`.

---

## Completed Work (do not redo)
- ✅ Workspace setup (CLAUDE.md, instructions.md, all config files)
- ✅ Ruflo MCP integration with Claude Code (Windows-compatible, cmd wrapper)
- ✅ Broker MVP Python (engine, schema, policy, config, __main__)
- ✅ Local cache backend (flat-file JSON, real, working)
- ✅ Ruflo adapter (sqlite3, real, round-trip proven)
- ✅ Input validation: `clamp_unit()` for confidence/importance in schema.py
- ✅ All retrieval limits in config.example.json
- ✅ `RUFLO_DB_PATH` env var chain (.env.example → engine.py)
- ✅ `.gitignore` includes `.swarm/`
- ✅ Swarm experiment documented in `docs/ruflo-swarm-report.md`
- ✅ All documentation synced to real state
- ✅ Git repo initialized, 23 files committed (`initial broker MVP with Ruflo sqlite integration`)
- ✅ Pushed to `https://github.com/ketchh/arbiter` (branch `main`)
- ✅ GitHub Actions Claude Code app installed on the repo

---

## Pending Work (priority order)

### 1. Supermemory adapter (highest architectural value)
- File: `broker/adapters/supermemory.py`
- Replace the stub with real Supermemory REST API calls.
- Prefer `urllib` or `http.client` over installing new packages.
- Keep the same `upsert(record)` / `retrieve(scope, limit)` interface as ruflo.py and local_cache.py.
- Guard all API calls behind `if not self.api_key: return` — graceful degradation when key is absent.
- Write a round-trip proof (write → retrieve from real API) when `SUPERMEMORY_API_KEY` is configured; document how to test it manually if the key is not present.
- Do not make Supermemory the sole backend — the broker policy layer decides routing.

### 2. Broker as local service (enables multi-client and VPS scenarios)
- Currently CLI only via `python -m broker dry-run`.
- Next direction: expose a minimal HTTP endpoint (port 8081 per config) so clients can POST events and GET context without importing the broker package directly.
- No cloud deployment yet — local first.

### 3. Automated tests
- No tests exist for the broker round-trip.
- Minimum viable: test `normalize_client_event → capture_event → retrieve` end-to-end against a temp sqlite DB (not the real `.swarm/memory.db`).

---

## Required First Task For The Next Agent
1. Perform a code review of every file currently in this workspace — findings first, ordered by severity.
2. If there are no blockers, proceed with the pending work listed above, in priority order.
3. Report what you did and what remains before calling task_complete.

---

## Architecture Rules (do not change without user approval)
- Broker MVP language: Python 3.11+
- Canonical memory backend: Supermemory (long-term, authoritative)
- Local working memory: Ruflo sqlite + local JSON cache (non-authoritative, derivable)
- Preferred current client adapter: Claude Code
- Long-term rule: client-agnostic, all adapters replaceable
- No secrets in committed files
- No autonomous package installation without explicit user approval
- Broker is the only layer allowed to define read/write memory policy across tools

---

## Mandatory Rule: Keep This File Up To Date

Every agent — human or AI — that completes a task **must** update this file before finishing.

**What to update:**
1. The `_Last updated_` line at the top — date + one-line summary of what changed.
2. Move completed items to the `## Completed Work` section (add ✅ prefix).
3. Remove or update items in `## Pending Work` to reflect what is actually next.
4. If new files were created, add them to the relevant table in `## Snapshot`.
5. If architecture decisions changed, update `## Architecture Rules` and `## Integration State`.

**Why this matters:**
- This file is the single source of truth for project continuity across sessions and agents.
- Without it being accurate, the next agent (or the user) has no reliable starting point.
- Outdated next steps waste time or cause regressions.

**Format for the last-updated line:**
```
_Last updated: YYYY-MM-DD (brief description of what changed). Read this file completely before touching anything._
```
