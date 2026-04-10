# MCP Integration and Claude Code Hooks

How to wire the Arbiter memory broker into Claude Code for automatic event capture and inline memory queries.

---

## Prerequisites

1. The broker package is installed: `pip install -e .` from the workspace root.
2. The broker server is running: `arbiter serve` or `python -m broker serve`.
3. (Optional) Set `BROKER_API_KEY` in `.env` if you want authenticated access.

---

## Part 1: MCP Resource Provider

The module `broker/mcp_resources.py` provides three resource proxies that call the broker HTTP API:

| Resource | Function | Description |
|----------|----------|-------------|
| `broker://health` | `get_health()` | Liveness check, returns project ID and active backends |
| `broker://retrieve/{scope}` | `retrieve_by_scope(scope, query)` | Retrieve memories filtered by scope (profile, project, episodic, procedural, governance) |
| `broker://metrics` | `get_metrics()` | Request counters, uptime, rate-limit hit count |

### CLI usage (for testing)

```bash
python -m broker.mcp_resources health
python -m broker.mcp_resources retrieve episodic
python -m broker.mcp_resources retrieve project --query "architecture"
python -m broker.mcp_resources metrics
```

### Library usage

```python
from broker.mcp_resources import get_health, retrieve_by_scope, get_metrics

health = get_health()
memories = retrieve_by_scope("project", query="broker architecture")
metrics = get_metrics()
```

### MCP server entry

The `.mcp.json` file includes an `arbiter-broker` entry. This registers the broker resource provider as an MCP server that Claude Code can discover. The entry uses `python -m broker.mcp_resources` as its command.

Environment variables `BROKER_URL` and `BROKER_API_KEY` are configurable in the MCP server entry.

---

## Part 2: Claude Code Hooks

The broker captures events automatically through Claude Code hooks. The hooks call `broker/hooks.py` CLI commands which POST to the running broker server.

### Events captured

| Hook | Event Type | Broker Scope | What it captures |
|------|-----------|-------------|-----------------|
| `PostToolUse` (Write/Edit/MultiEdit) | post-edit | episodic | File path of every edited file |
| `SubagentStop` | post-task | procedural | Task completion with task ID |
| `SessionStart` | session start | episodic | Session start event |
| `SessionEnd` | session end | episodic | Session end event |

### Manual setup

The `.claude/settings.json` file is protected and cannot be edited programmatically. Add the following hooks manually by editing `.claude/settings.json`:

**Add to the `PostToolUse` section**, inside the `Write|Edit|MultiEdit` matcher's hooks array:

```json
{
  "type": "command",
  "command": "cmd /c python -m broker.hooks post-edit --file \"%TOOL_INPUT_FILE_PATH%\"",
  "timeout": 5000
}
```

**Add to the `SessionStart` section**, inside the hooks array:

```json
{
  "type": "command",
  "command": "cmd /c python -m broker.hooks session --type start --session-id \"%SESSION_ID%\"",
  "timeout": 5000
}
```

**Add to the `SessionEnd` section**, inside the hooks array:

```json
{
  "type": "command",
  "command": "cmd /c python -m broker.hooks session --type end --session-id \"%SESSION_ID%\"",
  "timeout": 5000
}
```

**Add to the `SubagentStop` section**, inside the hooks array:

```json
{
  "type": "command",
  "command": "cmd /c python -m broker.hooks post-task --task-id \"%TASK_ID%\" --task \"subagent completed\"",
  "timeout": 5000
}
```

### Hook CLI reference

```bash
# Capture a completed task
python -m broker.hooks post-task --task-id TASK_123 --task "implemented feature X"

# Capture a failed task
python -m broker.hooks post-task --task-id TASK_123 --task "attempted feature X" --failed

# Capture a file edit
python -m broker.hooks post-edit --file src/main.py

# Capture session start
python -m broker.hooks session --type start --session-id sess_abc

# Capture session end
python -m broker.hooks session --type end --session-id sess_abc
```

Note: The `--success` flag was removed. Use `--failed` to mark a task or edit as failed; the default is success.

### Graceful degradation

All hook commands fail silently (log a warning, return `{"error": "UNREACHABLE"}`) if the broker server is not running. This means hooks will not break your Claude Code session even if you forget to start the broker.

---

## Part 3: Querying Memories from Claude Code

With the broker running, you can query memories inline during a Claude Code session:

### Via the MCP resource provider

If the `arbiter-broker` MCP server is started in Claude Code, the resource functions are available for tool calls.

### Via direct HTTP (Bash tool)

```bash
# Health check
curl http://127.0.0.1:8081/health

# Retrieve project memories
curl -X POST http://127.0.0.1:8081/retrieve \
  -H "Content-Type: application/json" \
  -d '{"scope_filters": ["project"], "query": "architecture"}'

# Retrieve all episodic memories
curl -X POST http://127.0.0.1:8081/retrieve \
  -H "Content-Type: application/json" \
  -d '{"scope_filters": ["episodic"]}'

# Check metrics
curl http://127.0.0.1:8081/metrics
```

### Via Python (in-session)

```python
from broker.mcp_resources import retrieve_by_scope
result = retrieve_by_scope("project", query="broker")
print(result)
```

---

## Verification

To verify the integration is working:

1. Start the broker: `arbiter serve`
2. In another terminal, test the health endpoint: `python -m broker.mcp_resources health`
3. Expected output: `{"status": "ok", "project_id": "...", "backends": [...]}`
4. Test a capture: `python -m broker.hooks post-task --task-id test_001 --task "verification test"`
5. Retrieve it: `python -m broker.mcp_resources retrieve procedural --query "verification"`
