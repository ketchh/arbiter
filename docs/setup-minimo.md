# Setup Minimo

## Goal
- Local-first bootstrap for a runtime-agnostic stack with Ruflo, Supermemory, and a memory broker.
- Claude Code is the current fast path because it is mature today, but it should stay replaceable.
- No secrets committed.
- Windows PowerShell-friendly commands by default.
- Allow the same memory and tool stack to move later to a VPS without redesigning the broker boundary.

## What Already Exists In This Workspace
- Persistent instructions for the current Claude Code adapter via `CLAUDE.md` -> `instructions.md`
- Minimal Ruflo project config in `claude-flow.config.json`
- Example env vars in `.env.example`
- Broker policy defaults in `broker/config.example.json`
- Runnable broker MVP code in `broker/`
- Real local Ruflo memory integration through `.swarm/memory.db`

## Manual Prerequisites
1. Install Git for Windows if missing.
2. Install Node.js 20+ and npm 9+.
3. Install Python 3.11+.
4. Decide whether your canonical memory backend will start as hosted Supermemory or as a temporary local store behind the broker.
5. Install Claude Code only if you want to use the current adapter path.

## Suggested Order
1. Confirm broker contract and env conventions
2. Validate broker MVP locally
3. Validate broker plus Ruflo local memory together
4. Decide canonical memory path
5. Attach the current client adapter, starting with Claude Code if desired
6. Move shared services to VPS when the local contract is stable
7. Review pass and integration tightening

## Recommended Path For Your Current Goal
1. Do not install the Supermemory Claude plugin first.
2. Do not make Claude Code responsible for persistence.
3. Start Claude Code in this workspace and ask it to validate the current broker MVP first.
4. Keep Supermemory behind the broker API boundary.
5. Keep Ruflo as local working memory and orchestration while the broker becomes the single policy layer.
6. Only then decide whether to attach Claude Code directly to Supermemory, to your broker, or to both.

## Commands

### Current adapter path: Claude Code install
```powershell
irm https://claude.ai/install.ps1 | iex
claude --version
```

### Ruflo quick start
```powershell
npx ruflo@latest init
```

### Current adapter path: attach Ruflo to Claude Code
```powershell
claude mcp add ruflo -- npx ruflo@latest mcp start
claude mcp list
```

### Current adapter path: Supermemory plugin from inside Claude Code
```text
/plugin marketplace add supermemoryai/claude-supermemory
/plugin install claude-supermemory
```

### Later server path: move the shared stack to VPS
- Broker service runs on the VPS and exposes the same normalization and retrieval contract.
- Ruflo runs on the VPS as orchestrator or MCP service.
- Canonical memory runs either as hosted Supermemory or as a self-hosted Supermemory deployment if you have that entitlement.
- Local machines stay thin: client adapter, auth, and project workspace only.

### Persistent PowerShell env vars
```powershell
Add-Content $PROFILE '$env:SUPERMEMORY_CC_API_KEY="sm_..."'
Add-Content $PROFILE '$env:CLAUDE_FLOW_LOG_LEVEL="info"'
```

### Optional current-shell env vars
```powershell
$env:SUPERMEMORY_CC_API_KEY="sm_..."
$env:CLAUDE_FLOW_TOOL_MODE="develop"
$env:CLAUDE_FLOW_TOOL_GROUPS="implement,test,fix,memory"
```

## Notes
- The Supermemory Claude Code plugin currently requires a Supermemory Pro plan.
- Public Supermemory docs support hosted API usage by default; self-hosting exists, but the published deployment guide is currently enterprise-oriented.
- The Claude Supermemory plugin code supports custom API and auth URLs, but the documented happy path is still the hosted service.
- Prefer generic broker and Supermemory credentials over Claude-specific env names whenever both are available.
- This workspace has not yet executed any installer or login flow.
- The next implementation step should happen only after a review of the current files.
