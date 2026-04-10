@docs/memory-broker.md

# Continuation Instructions

_Last updated: 2026-04-10 (code review + 17 fixes via SPARC swarm, 38 tests passing). Read this file completely before touching anything._

---

## Snapshot: What Exists Right Now

### Workspace root (`C:\Users\aless\Documents\ancora non lo so\SIR\`)
```
pyproject.toml                 ← pip install -e . / arbiter CLI entry point
Dockerfile                     ← container deployment (python:3.12-slim)
CLAUDE.md                      ← workspace entrypoint for Claude Code
instructions.md                ← this file (imported by CLAUDE.md)
claude-flow.config.json        ← Ruflo project config
.env.example                   ← all env var placeholders (no secrets)
.gitignore                     ← includes .swarm/, .env, .broker/
broker/                        ← Python memory broker MVP
docs/                          ← architecture docs
tests/                         ← unittest round-trip tests (17 tests, all passing)
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
| `server.py` | **REAL** | HTTP server (http.server); endpoints: /capture, /retrieve, /explain, /upsert, /cache, /health; CORS; default 127.0.0.1:8081 |
| `adapters/supermemory.py` | **REAL** | urllib-based REST adapter for Supermemory API v3; POST /v3/documents + POST /v3/search; graceful NO_KEY degradation |
| `hooks.py` | **REAL** | Ruflo hook bridge: post-task, post-edit, session events → broker /capture; CLI + library API |

### Documentation (`docs/`)
| File | Content |
|------|---------|
| `memory-broker.md` | full architecture + "Current Practical Role" section |
| `topologia-server.md` | server topology |
| `code-review.md` | detailed code review (20 findings, 17 fixed) |

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
- Adapter at `broker/adapters/supermemory.py` is **real code** (urllib + Supermemory REST API v3).
- **Live and proven**: write (POST /v3/documents) + search (POST /v3/search) both return 200.
- Graceful degradation: works as a no-op when `SUPERMEMORY_API_KEY` is not set.
- API key configured in `.env` (not committed).
- Do not bypass the broker layer — all writes must go through `engine.py`.

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
- ✅ Supermemory adapter: real urllib REST implementation (v3 API), graceful NO_KEY degradation
- ✅ HTTP server (`broker/server.py`): /capture, /retrieve, /explain, /upsert, /cache, /health; CORS; CLI `python -m broker serve`
- ✅ Automated tests: 17 unit tests + 13 HTTP tests (30 total)
- ✅ Supermemory full round-trip proven: write (POST /v3/documents) + search (POST /v3/search) + chunk parsing
- ✅ Bearer auth on HTTP server: `BROKER_API_KEY` env var, /health stays public
- ✅ Structured request logging (method, path, status, duration, client IP)
- ✅ Per-IP rate limiting (BROKER_RATE_LIMIT, BROKER_RATE_WINDOW env vars)
- ✅ `/metrics` endpoint (request counters, uptime, rate-limit hits)
- ✅ Ruflo hook bridge (`broker/hooks.py`): post-task, post-edit, session → broker /capture
- ✅ Ruflo MCP memory: broker config + architecture stored in `broker` namespace
- ✅ 38 tests total (17 unit + 15 HTTP + 6 hooks), all passing
- ✅ pip-installable (`pip install -e .` → `arbiter` CLI command)
- ✅ CLI: serve, dry-run, capture, retrieve, status
- ✅ Dockerfile for container/VPS deployment
- ✅ Code review: 20 findings documented in `docs/code-review.md` (3 HIGH, 9 MEDIUM, 6 LOW, 2 INFO)
- ✅ SEC-01: HTTP body size limit (`BROKER_MAX_BODY_SIZE` env var, default 1MB, returns 413)
- ✅ SEC-02: `/upsert` now validates confidence/importance with `clamp_unit()`
- ✅ SEC-03: CORS origin configurable via `BROKER_CORS_ORIGIN` env var
- ✅ BUG-01: Metrics status tracking now uses actual handler return codes
- ✅ BUG-02: Query parameter propagated to all backends (supermemory search, ruflo SQL LIKE, local_cache substring)
- ✅ BUG-03: `body.get()` replaces `body.pop()` in `_handle_capture` (no input mutation)
- ✅ BUG-04: Invalid scope/memory_type now returns 400 with detail instead of 500
- ✅ BUG-05: Removed redundant `--success` flag from hooks CLI (was always True)
- ✅ PERF-01: `PRAGMA journal_mode=WAL` moved to `_ensure_db()` (runs once, not per-connection)
- ✅ PERF-02: Ruflo retrieve uses SQL-level user/workspace filtering + batched access_count UPDATE
- ✅ ARCH-02: `upsert_memory()` synthetic event now includes confidence, memory_type, subject
- ✅ ARCH-03: `clamp_unit()` uses module-level logger instead of lazy import
- ✅ DOC-01: README test count updated to 38
- ✅ All handlers return status codes for accurate metrics tracking
- ✅ 38 tests still passing after all fixes

---

## Pending Work (priority order)

### 1. Multi-workspace isolation testing
- Test container tags isolation with 2+ workspaces writing to the same Supermemory org.
- Verify that retrieve scoped by workspace_id returns only matching records.

### 2. VPS deployment
- Dockerfile ready — test with `docker build -t arbiter . && docker run -p 8081:8081 --env-file .env arbiter`.
- Document systemd/PM2 service configuration for non-Docker setups.

### 3. Claude Code custom tool / MCP resource
- Register broker endpoints as MCP resources so Claude Code can query memory inline.
- Explore using Ruflo `hooks_init` to wire broker hooks into `.claude/settings.json` automatically.

---

## Required First Task For The Next Agent
1. Code review of all workspace files, report findings by severity.
2. Proceed with the pending work listed above, in priority order.
3. Report what you did and what remains before finishing.

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
