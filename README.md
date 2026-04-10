# Arbiter

A runtime-agnostic memory broker that sits between AI clients and memory backends, providing a single policy layer for read/write routing, normalization, and retrieval.

## Why

AI tools (Claude Code, IDE extensions, automation scripts) each manage memory differently. Arbiter centralizes memory policy so that:

- No single client owns how memories are stored or retrieved
- Backends (local cache, Ruflo, Supermemory) are swappable without client changes
- Every write carries provenance, scope, confidence, and importance
- The same memory plane works across devices, workspaces, and clients

## Architecture

```
  Clients                    Broker                     Backends
  -------                    ------                     --------
  Claude Code  ──┐
  IDE plugins  ──┼──>  normalize ──> policy ──┬──>  Supermemory (canonical)
  CLI scripts  ──┤          │                 ├──>  Ruflo sqlite (working)
  HTTP clients ──┘     retrieve  <────────────┴──>  Local JSON cache
```

## Quick Start

```bash
# Clone
git clone https://github.com/ketchh/arbiter.git
cd arbiter

# Copy env and configure
cp .env.example .env
# Edit .env with your API keys (optional — works without them)

# Run the dry-run demo
python -m broker dry-run

# Start the HTTP server (default: http://127.0.0.1:8081)
python -m broker serve
```

### Requirements

- Python 3.11+
- No external dependencies (stdlib only)

## API

The broker exposes a local HTTP API:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/capture` | Normalize and store a client event |
| `POST` | `/retrieve` | Retrieve context by scope |
| `POST` | `/explain` | Preview retrieval without fetching |
| `POST` | `/upsert` | Direct memory record upsert |
| `DELETE` | `/cache` | Flush local cache |
| `GET` | `/health` | Liveness check |

### Example: capture an event

```bash
curl -X POST http://127.0.0.1:8081/capture \
  -H "Content-Type: application/json" \
  -d '{
    "client": "my-tool",
    "scope": "project",
    "memory_type": "decision",
    "subject": "auth-rewrite",
    "content": "Switched from JWT to session tokens for compliance.",
    "confidence": 0.9,
    "importance": 0.8
  }'
```

### Example: retrieve context

```bash
curl -X POST http://127.0.0.1:8081/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "auth decisions",
    "scope_filters": ["project", "governance"]
  }'
```

## Memory Scopes

| Scope | What it holds |
|-------|---------------|
| `profile` | Stable user preferences and identity facts |
| `project` | Architecture, conventions, explicit decisions |
| `episodic` | Recent sessions, attempts, failures |
| `procedural` | Workflows, tool preferences, successful patterns |
| `governance` | Rules, allowed autonomy, review constraints |

## Backends

| Backend | Role | Status |
|---------|------|--------|
| **Supermemory** | Canonical long-term memory | Ready (needs `SUPERMEMORY_API_KEY`) |
| **Ruflo sqlite** | Local working memory and orchestration cache | Working |
| **Local JSON cache** | Fast local fallback, one file per scope | Working |

The write policy decides which backends receive each write based on scope and importance. Low-importance episodic events skip the canonical backend automatically.

## Tests

```bash
python -m unittest tests.test_broker_roundtrip -v
```

17 tests covering normalization, policy routing, round-trips against local cache and Ruflo sqlite, Supermemory graceful degradation, and dry-run behavior.

## Project Structure

```
broker/
  __main__.py          CLI entry (dry-run, serve)
  engine.py            Core broker: normalize, capture, retrieve
  schema.py            BrokerEvent, MemoryRecord, MemoryScope
  policy.py            Write routing by scope and importance
  config.py            Config loader (.env + JSON, env var overrides)
  server.py            HTTP server (stdlib http.server)
  adapters/
    supermemory.py     Supermemory REST API v3 (urllib)
    ruflo.py           Ruflo sqlite3 adapter
    local_cache.py     Flat-file JSON backend
tests/
  test_broker_roundtrip.py
docs/
  memory-broker.md     Architecture and policy reference
  setup-minimo.md      Setup guide
```

## License

Private repository.
