# Memory Broker

## Purpose
- Provide one policy layer between clients and memory backends.
- Avoid double truth between Ruflo memory and Supermemory.
- Keep memory portable across devices and replaceable in the future.
- Keep client runtimes replaceable in the future.
- Allow one shared memory and tool plane to serve multiple workspaces and multiple devices.

## Non-Negotiable Rules
- Supermemory is the canonical long-term memory backend.
- Ruflo memory is non-authoritative and should only hold working memory, cached retrieval, routing hints, and derived patterns.
- No client runtime, including Claude Code, may become authoritative for memory policy, memory schema, or durable storage decisions.
- Every durable write needs provenance, scope, timestamp, confidence, and importance.
- Adapters must not bypass the broker write policy.
- Client-specific events must be normalized into a broker-owned schema before policy evaluation.
- Tool adaptation can suggest changes, but must not auto-enable new tools without user approval.

## Memory Scopes
- `profile`: stable user preferences and persistent identity facts
- `project`: architecture, conventions, and explicit decisions
- `episodic`: recent sessions, attempts, failures, TODO continuity
- `procedural`: workflows, tool preferences, and successful patterns
- `governance`: rules, allowed autonomy, and review constraints

## Recommended Write Policy
| Scope | Supermemory | Ruflo | Local cache |
| --- | --- | --- | --- |
| profile | yes | no | optional |
| project | yes | optional derived copy | yes |
| episodic | yes | yes | yes |
| procedural | yes | yes | yes |
| governance | yes | no | yes |

## Retrieval Policy
- Broker merges retrieved context by scope.
- Profile and governance context should be injected first.
- Project and procedural context should be ranked ahead of episodic context when a task is architecture- or implementation-heavy.
- Ruflo may enrich ranking locally, but must not override canonical fact storage.
- Retrieval must always be scoped by user plus workspace or project identifiers so one portable memory plane can safely serve multiple repositories.

## Deployment Direction
- Local development should use the same broker contract as the future VPS deployment.
- The VPS should be treated as the long-lived home for broker, orchestrator, and shared memory services.
- Each project workspace should remain isolated through broker-level scoping rather than separate ad hoc memory silos inside each client.
- The VPS itself can have its own infrastructure workspace, distinct from user project workspaces.

## Minimal Event Shape
```json
{
  "id": "evt_001",
  "client": "claude-code",
  "scope": "project",
  "memory_type": "decision",
  "subject": "workspace:sir",
  "content": "Supermemory is the canonical durable memory backend.",
  "confidence": 0.95,
  "importance": 0.85,
  "source": "manual_bootstrap",
  "provenance": {
    "actor": "workspace_bootstrap",
    "file": "instructions.md"
  },
  "timestamp": "2026-04-10T00:00:00Z"
}
```

## Minimal Broker Interface
- `load_config()`
- `normalize_client_event(raw_event, client_name)`
- `capture_event(event)`
- `upsert_memory(record)`
- `retrieve_context(query, scope_filters)`
- `explain_retrieval(query)`
- `flush_local_cache()`

## MVP Default
- First implementation target: Python 3.11+
- Local-first execution model
- Dry-run mode before real writes
- Ruflo adapter now performs real local reads and writes against `.swarm/memory.db`
- Supermemory adapter remains a stub until the hosted or self-hosted backend is chosen
- Claude Code is the first client adapter, not a special-case storage path

## Current Practical Role
- The broker is now the policy and normalization layer in front of multiple memory backends.
- It converts raw client events into a broker-owned schema before any write happens.
- It decides which backends receive each write based on scope and policy.
- It currently writes to both the local JSON cache and Ruflo's local sqlite memory.
- It retrieves scoped context from both local cache and Ruflo through one interface.
- It keeps Supermemory optional and replaceable until the remote memory target is finalized.

## Architecture Sketch
```text
Client adapters
  |- Claude Code (current)
  |- other CLIs
  |- IDE integrations
  |- automation jobs
        |
        v
    Memory Broker
     |    |    |
     |    |    +-- local cache
     |    +------- Ruflo working memory / routing hints
     +------------ Supermemory canonical memory
```
