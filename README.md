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
# Clone and install
git clone https://github.com/ketchh/arbiter.git
cd arbiter
pip install -e .

# Copy env and configure
cp .env.example .env
# Edit .env — add SUPERMEMORY_API_KEY for long-term memory (optional)

# Start the server
arbiter serve

# In another terminal — send a memory
arbiter capture "Switched auth from JWT to sessions" --scope project --type decision

# Retrieve context
arbiter retrieve "auth decisions" --scopes project

# Check status
arbiter status
```

### Docker

```bash
docker build -t arbiter .
docker run -p 8081:8081 --env-file .env arbiter
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
| `GET` | `/health` | Liveness check (no auth required) |
| `GET` | `/metrics` | Request counters and uptime |

### Authentication

Set `BROKER_API_KEY` in `.env` to require Bearer token auth on all endpoints except `/health`:

```bash
# In .env
BROKER_API_KEY=your-secret-key

# In requests
curl -H "Authorization: Bearer your-secret-key" http://127.0.0.1:8081/capture ...
```

When `BROKER_API_KEY` is not set, the server runs in open mode (suitable for local use).

### Rate Limiting

Per-IP sliding-window rate limiting is enabled by default (60 requests per 60 seconds). Configure via:

```bash
BROKER_RATE_LIMIT=60   # max requests per window (0 = disabled)
BROKER_RATE_WINDOW=60  # window in seconds
```

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
python -m unittest discover tests -v
```

38 tests covering (17 unit + 15 HTTP + 6 hooks):
- Event normalization, clamping, policy routing
- Local cache and Ruflo sqlite round-trips
- Supermemory graceful degradation (no key) and live API integration
- HTTP server endpoints, CORS, auth enforcement
- Rate limiting and metrics
- Ruflo hook bridge (post-task, post-edit, session events)

## Project Structure

```
broker/
  __main__.py          CLI: serve, dry-run, capture, retrieve, status
  engine.py            Core broker: normalize, capture, retrieve
  schema.py            BrokerEvent, MemoryRecord, MemoryScope
  policy.py            Write routing by scope and importance
  config.py            Config loader (.env + JSON, env var overrides)
  server.py            HTTP server with auth, rate limiting, metrics
  hooks.py             Ruflo hook bridge (auto-capture events)
  adapters/
    supermemory.py     Supermemory REST API v3 (urllib)
    ruflo.py           Ruflo sqlite3 adapter
    local_cache.py     Flat-file JSON backend
tests/
  test_broker_roundtrip.py   17 unit tests
  test_server_http.py        15 HTTP integration tests
  test_hooks.py              6 hook bridge tests
pyproject.toml         Package config (pip install -e .)
Dockerfile             Container deployment
docs/
  memory-broker.md     Architecture and policy reference
```

## CLI Reference

```
arbiter serve                          Start the HTTP server
arbiter dry-run                        Demo event flow without side effects
arbiter capture "text" -s project      Send a memory event
arbiter retrieve "query" --scopes project,episodic
arbiter status                         Health + metrics from running server
```

## License

MIT
