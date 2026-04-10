@instructions.md

# Workspace Rules

## Mission
- This workspace bootstraps a minimal local stack for a runtime-agnostic coding workflow with Ruflo, Supermemory, and an external memory broker.
- Claude Code is the current preferred client adapter, not a required long-term foundation.
- Treat Supermemory as canonical long-term memory.
- Treat Ruflo as orchestration, routing, hooks, and optional local working memory.
- Treat the broker as the only layer allowed to define read/write memory policy across tools.
- No client runtime is allowed to become the source of truth for memory policy or project continuity.

## First Action In Every Fresh Session
- Start with a code review of all workspace files created so far.
- Report findings first, ordered by severity, with concrete file references.
- If there are no findings, state that explicitly, then continue with the next pending setup step.

## Working Rules
- Prefer the documented setup state over assumptions.
- Keep the setup minimal, reversible, and Windows-friendly.
- Do not write secrets to versioned files.
- Prefer Python for the first broker MVP unless the user redirects the implementation language.
- Before expanding scope, make the current step runnable or at least configuration-complete.

## Current Target
- All three backends are implemented (Ruflo sqlite, local JSON cache, Supermemory REST API).
- Supermemory activation requires only setting `SUPERMEMORY_API_KEY` in `.env`.
- Next milestone: live Supermemory round-trip proof, then broker service hardening for VPS deployment.
