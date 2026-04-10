"""Normalized event schema and memory record — client-neutral."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import logging

log = logging.getLogger(__name__)


class MemoryScope(str, Enum):
    PROFILE = "profile"
    PROJECT = "project"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"
    GOVERNANCE = "governance"


class MemoryType(str, Enum):
    DECISION = "decision"
    FACT = "fact"
    PREFERENCE = "preference"
    CONVENTION = "convention"
    EPISODE = "episode"
    WORKFLOW = "workflow"
    RULE = "rule"


@dataclass
class Provenance:
    actor: str = ""
    file: str = ""
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v}


@dataclass
class BrokerEvent:
    """Client-neutral normalized event.

    Every event entering the broker is converted to this shape,
    regardless of which client produced it.
    """

    id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    client: str = ""
    user_id: str = ""
    workspace_id: str = ""
    scope: MemoryScope = MemoryScope.EPISODIC
    memory_type: MemoryType = MemoryType.FACT
    subject: str = ""
    content: str = ""
    confidence: float = 0.5
    importance: float = 0.5
    source: str = ""
    provenance: Provenance = field(default_factory=Provenance)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scope"] = self.scope.value
        d["memory_type"] = self.memory_type.value
        d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class MemoryRecord:
    """Stored memory record — what backends persist."""

    id: str = field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:12]}")
    event_id: str = ""
    user_id: str = ""
    workspace_id: str = ""
    scope: MemoryScope = MemoryScope.EPISODIC
    memory_type: MemoryType = MemoryType.FACT
    subject: str = ""
    content: str = ""
    confidence: float = 0.5
    importance: float = 0.5
    provenance: Provenance = field(default_factory=Provenance)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scope"] = self.scope.value
        d["memory_type"] = self.memory_type.value
        d["provenance"] = self.provenance.to_dict()
        return d

    @classmethod
    def from_event(cls, event: BrokerEvent) -> MemoryRecord:
        return cls(
            event_id=event.id,
            user_id=event.user_id,
            workspace_id=event.workspace_id,
            scope=event.scope,
            memory_type=event.memory_type,
            subject=event.subject,
            content=event.content,
            confidence=event.confidence,
            importance=event.importance,
            provenance=event.provenance,
        )


def clamp_unit(value: float, field_name: str) -> float:
    """Clamp a float to [0.0, 1.0] and warn on out-of-range input."""
    clamped = max(0.0, min(1.0, value))
    if clamped != value:
        log.warning(
            "%s=%.4f out of [0,1], clamped to %.4f", field_name, value, clamped,
        )
    return clamped


def normalize_client_event(
    raw: dict[str, Any],
    client_name: str,
    user_id: str,
    workspace_id: str,
) -> BrokerEvent:
    """Convert a raw client event dict into a BrokerEvent.

    Each client adapter may send events in slightly different shapes.
    This function maps them into the broker-owned schema.
    """
    return BrokerEvent(
        id=raw.get("id", f"evt_{uuid.uuid4().hex[:12]}"),
        client=client_name,
        user_id=user_id,
        workspace_id=workspace_id,
        scope=MemoryScope(raw.get("scope", "episodic")),
        memory_type=MemoryType(raw.get("memory_type", raw.get("memoryType", "fact"))),
        subject=raw.get("subject", ""),
        content=raw.get("content", ""),
        confidence=clamp_unit(float(raw.get("confidence", 0.5)), "confidence"),
        importance=clamp_unit(float(raw.get("importance", 0.5)), "importance"),
        source=raw.get("source", client_name),
        provenance=Provenance(
            actor=raw.get("provenance", {}).get("actor", client_name),
            file=raw.get("provenance", {}).get("file", ""),
            session_id=raw.get("provenance", {}).get("session_id", ""),
        ),
        timestamp=raw.get(
            "timestamp", datetime.now(timezone.utc).isoformat()
        ),
    )
