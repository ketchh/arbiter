"""Write policy layer — decides where a memory record is routed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from broker.config import BrokerConfig
    from broker.schema import BrokerEvent


@dataclass
class WriteDecision:
    """Result of evaluating the write policy for one event."""

    scope: str
    backends: list[str]
    reason: str

    def explain(self) -> str:
        if not self.backends:
            return f"[{self.scope}] BLOCKED — {self.reason}"
        return f"[{self.scope}] -> {', '.join(self.backends)} — {self.reason}"


def evaluate_write(event: BrokerEvent, config: BrokerConfig) -> WriteDecision:
    """Decide which backends receive a write for this event."""
    scope = event.scope.value
    backends = config.write_policy.get(scope, [])

    if not backends:
        return WriteDecision(
            scope=scope,
            backends=[],
            reason=f"no backends configured for scope '{scope}'",
        )

    # Filter: if importance is below 0.3 and scope is episodic, skip canonical
    if scope == "episodic" and event.importance < 0.3:
        backends = [b for b in backends if b != "supermemory"]
        reason = "low-importance episodic — skipping canonical, cache only"
    else:
        reason = f"standard write-through for scope '{scope}'"

    return WriteDecision(scope=scope, backends=backends, reason=reason)
