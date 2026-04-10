# Topologia Server-First

## Intent
- Keep local clients replaceable.
- Keep memory and tool services persistent on a server.
- Preserve workspace isolation without creating one separate memory system per client.

## Recommended Topology
```text
Laptop or desktop clients
  |- Claude Code
  |- other coding agents
  |- IDE integrations
        |
        v
    Broker API / CLI
        |
        +-- Ruflo orchestration or MCP service
        +-- canonical memory backend
        +-- local cache or derived memory store

VPS infrastructure workspace
  |- broker repo
  |- deployment config
  |- observability and admin scripts
```

## What Lives On The VPS
- Broker service and broker policy config
- Ruflo service or MCP endpoint
- Shared credentials and routing logic
- Canonical memory backend if self-hosted
- Local cache, logs, and observability

## What Stays Local On Each Device
- The coding client itself
- User auth material for the chosen client
- The checked-out project workspace
- Thin client adapter settings only

## Workspace Strategy
- Use one stable `userId` across all devices.
- Use one `workspaceId` or `projectId` per repository.
- Use a separate `workspaceId` for the VPS infrastructure workspace.
- Never rely on the client tool to infer canonical memory scope on its own.

## Practical Recommendation
- First make the broker runnable locally.
- Then move the same broker process to a VPS.
- Add Ruflo on the VPS after the broker contract is stable.
- Attach Claude Code last, as a client of that shared system.