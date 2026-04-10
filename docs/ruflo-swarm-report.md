# Ruflo Swarm Experiment Report

**Date:** 2026-04-10  
**Session:** Claude Code + Ruflo MCP (stdio, PID 37944)  
**Ruflo version:** 3.0.0

## MCP Tools Invoked

| # | Tool | Arguments (key fields) | Response ID / Key Field |
|---|------|----------------------|------------------------|
| 1 | `mcp_status` | (none) | `running: true, pid: 37944` |
| 2 | `system_status` | `verbose: true` | `status: healthy, version: 3.0.0` |
| 3 | `swarm_init` | `topology: hierarchical, maxAgents: 4, strategy: specialized` | `swarmId: swarm-1775784058204-e8946w` |
| 4 | `agent_spawn` | `agentId: agent-reviewer, agentType: researcher, domain: code-analysis, model: haiku` | `status: registered` |
| 5 | `agent_spawn` | `agentId: agent-planner, agentType: implementer, domain: code-analysis, model: haiku` | `status: registered` |
| 6 | `task_create` | `type: research, priority: high, assignTo: [agent-reviewer]` | `taskId: task-1775784087543-d9qtak` |
| 7 | `task_create` | `type: research, priority: high, assignTo: [agent-planner]` | `taskId: task-1775784087565-rbckdt` |
| 8 | `swarm_health` | `swarmId: swarm-1775784058204-e8946w` | `healthy: true, checks: all ok` |
| 9 | `agent_list` | (none) | `total: 2, both idle, health: 1` |
| 10 | `task_list` | (none) | `total: 2, both pending` |
| 11 | `task_update` | `taskId: ...d9qtak, status: in_progress, progress: 50` | `success: true` |
| 12 | `task_update` | `taskId: ...rbckdt, status: in_progress, progress: 30` | `success: true` |
| 13 | `memory_store` | `key: broker:adapter:ruflo:test-write, namespace: broker, value: {broker record}, tags: [broker, adapter-test, swarm-experiment]` | `stored: true, hasEmbedding: true, 384 dims, 3087ms` |
| 14 | `memory_search` | `query: ruflo adapter broker integration, namespace: broker, limit: 3` | `1 result, similarity: 0.31, 278ms` |
| 15 | `memory_retrieve` | `key: broker:adapter:ruflo:test-write, namespace: broker` | `found: true, value intact, accessCount: 1` |
| 16 | `task_complete` | `taskId: ...d9qtak, result: {analysis findings}` | `status: completed` |
| 17 | `task_complete` | `taskId: ...rbckdt, result: {implementation plan}` | `status: completed` |
| 18 | `swarm_status` | `swarmId: swarm-1775784058204-e8946w` | `status: running, agentCount: 0` |
| 19 | `agent_status` | `agentId: agent-reviewer` | `idle, health: 1, taskCount: 1` |
| 20 | `agent_status` | `agentId: agent-planner` | `idle, health: 1, taskCount: 1` |
| 21 | `swarm_shutdown` | `swarmId: swarm-1775784058204-e8946w, graceful: true` | `terminated: true` |

**Total MCP tool calls: 21**

## Swarm State Summary

- **Swarm ID:** `swarm-1775784058204-e8946w`
- **Topology:** hierarchical
- **Strategy:** specialized
- **Max agents:** 4
- **Agents spawned:** 2 (`agent-reviewer`, `agent-planner`)
- **Tasks created:** 2 (both completed)
- **Swarm health:** healthy throughout (coordinator ok, persistence ok)
- **Final state:** gracefully shut down

## Agent State

| Agent ID | Type | Domain | Status at end | Health | Tasks |
|----------|------|--------|---------------|--------|-------|
| agent-reviewer | researcher | code-analysis | idle | 1.0 | 1 completed |
| agent-planner | implementer | code-analysis | idle | 1.0 | 1 completed |

## Swarm Functional: YES / NO?

**YES** — with qualifications.

The swarm infrastructure works: init, spawn, task assignment, status tracking, health checks, task lifecycle (pending -> in_progress -> completed), and graceful shutdown all function correctly.

**Qualifications:**
- Agents are coordination records, not autonomous executors. The `note` field on spawn says: "Agent registered for coordination. Use Claude Code Task tool or claude -p to execute work." This means Ruflo agents track state and routing, but the actual work execution happens outside Ruflo (in Claude Code or another runtime).
- `swarm_status.agentCount` reported 0 even though `agent_list` showed 2 agents. The swarm coordinator and the agent registry may have separate counting.
- The swarm is a coordination layer, not an execution layer. This is consistent with the workspace architecture: Ruflo is for orchestration and working memory, not for running code.

## Memory Integration Test Results

- `memory_store`: writes a structured broker record to Ruflo's sql.js + HNSW backend. Embedding generated automatically (384 dims, not the 768 in config — cosmetic mismatch).
- `memory_search`: semantic search works. Returned the stored record with similarity 0.31 (low threshold needed).
- `memory_retrieve`: exact key lookup works. Full value round-tripped correctly.

## Swarm Task Findings

### Task 1: Which adapter to replace first?

**Answer: Ruflo adapter**, because:
- Ruflo MCP memory tools are already live and proven in this session
- Supermemory requires an API key and hosted backend not yet configured
- The `memory_store` / `memory_search` / `memory_retrieve` tools map cleanly to the broker adapter's `upsert` and `retrieve` interface

### Task 2: Implementation plan for Ruflo adapter

**Field mapping (upsert):**
| MemoryRecord field | Ruflo memory_store param |
|-------------------|-------------------------|
| `id` | `key` |
| `scope.value` | `namespace` |
| `to_dict()` | `value` |
| `subject` + scope tags | `tags` |

**Field mapping (retrieve):**
| Broker retrieve param | Ruflo tool |
|----------------------|------------|
| `scope` | `memory_search namespace` or `memory_list namespace` |
| query string | `memory_search query` |
| `limit` | `memory_search limit` |
| results | parse `value` back to record dicts |

**Integration blocker:** The broker's `RufloBackend` is a Python class. It cannot directly call MCP tools (which are JSON-RPC over stdio). Three options:
1. **Broker calls Ruflo via HTTP** — requires Ruflo to expose an HTTP endpoint
2. **Broker reads Ruflo's sqlite DB directly** — simplest for local-first MVP, same `.swarm/memory.db`
3. **Broker spawns `npx ruflo` commands** — works but slow

**Recommended next step:** Option 2 (direct sqlite access) for the local MVP, with a clean interface that can switch to HTTP when the broker moves to a VPS.

## Gaps and Anomalies

1. `memory_store` generates 384-dim embeddings; `claude-flow.config.json` and `.swarm/schema.sql` expect 768. Cosmetic — the HNSW index self-configures.
2. `memory_search` similarity was 0.31 for a directly relevant query. Threshold tuning or query phrasing matters.
3. `swarm_status.agentCount` was 0 while `agent_list.total` was 2. Minor state inconsistency.
4. Agents don't execute work autonomously — they are coordination records. Actual execution is delegated to Claude Code tasks or external processes.

## Changes Applied to the Repo

1. **`.gitignore`**: added `.swarm/` to prevent committing Ruflo's binary sqlite DB.

## Recommended Next Step

Replace `broker/adapters/ruflo.py` stub with a real implementation that reads/writes Ruflo's sqlite DB at `.swarm/memory.db` using Python's built-in `sqlite3` module. This requires no new packages and keeps the local-first constraint. The adapter should:
- Write broker `MemoryRecord` dicts as JSON into Ruflo's `memory_entries` table
- Use `namespace` = broker scope for isolation
- Read back with scope-filtered queries
- Preserve compatibility with Ruflo MCP tools reading the same DB
