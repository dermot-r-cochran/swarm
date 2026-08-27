"""
EPISTEME Data Models

Defines the core data structures for beliefs and evidence.
Beliefs are never overwritten; only new revisions are appended.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class BeliefType(str, Enum):
    """Type taxonomy for beliefs."""

    FACT = "FACT"
    THEORY = "THEORY"
    OPINION = "OPINION"
    FICTION = "FICTION"


class BeliefState(str, Enum):
    """Lifecycle state of a belief.

    ``REVISED`` is part of the spec's taxonomy but currently has no
    producer: ``EpistemicCore.resolve_state`` never returns it and no
    writer sets it. It is retained deliberately — it is public API and a
    stored-state vocabulary — rather than removed silently; giving it a
    producer is a design decision, not a cleanup.
    """

    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    REVISED = "REVISED"
    UNKNOWN = "UNKNOWN"
    UNDECIDED = "UNDECIDED"


@dataclass
class Evidence:
    """
    A piece of evidence that may support or contradict a belief.

    Attributes:
        summary:       Human-readable description of the evidence.
        reliability:   Reliability score in [0, 1].
        context_hash:  SHA-256 hash of the originating context.
        timestamp:     UTC timestamp of when the evidence was generated.
        id:            Unique identifier (auto-generated if not provided).
    """

    summary: str
    reliability: float
    context_hash: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str | None = field(default=None)

    def __post_init__(self) -> None:
        if not 0.0 <= self.reliability <= 1.0:
            raise ValueError(
                f"Evidence reliability must be in [0, 1], got {self.reliability}"
            )
        if self.id is None:
            payload = json.dumps(
                {
                    "summary": self.summary,
                    "reliability": self.reliability,
                    "context_hash": self.context_hash,
                    "timestamp": self.timestamp.isoformat(),
                },
                sort_keys=True,
            )
            self.id = hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class Belief:
    """
    An explicit, typed belief object with confidence and evidence references.

    Attributes:
        statement:            The belief statement.
        type:                 Belief type (FACT / THEORY / OPINION / FICTION).
        confidence:           Confidence score in [0, 1].
        domain:               Semantic domain the belief belongs to.
        evidence_ids:         IDs of supporting evidence.
        counter_evidence_ids: IDs of contradicting evidence.
        state:                Lifecycle state.
        id:                   Unique identifier (auto-generated if not provided).
        created_at:           UTC timestamp of initial creation.
    """

    statement: str
    type: BeliefType
    confidence: float
    domain: str
    evidence_ids: list[str] = field(default_factory=list)
    counter_evidence_ids: list[str] = field(default_factory=list)
    state: BeliefState = BeliefState.ACTIVE
    id: str | None = field(default=None)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Belief confidence must be in [0, 1], got {self.confidence}"
            )
        if isinstance(self.type, str):
            self.type = BeliefType(self.type)
        if isinstance(self.state, str):
            self.state = BeliefState(self.state)
        if self.id is None:
            payload = json.dumps(
                {
                    "statement": self.statement,
                    "domain": self.domain,
                    "created_at": self.created_at.isoformat(),
                },
                sort_keys=True,
            )
            self.id = hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class BeliefRevision:
    """
    An immutable record of a belief update.

    Beliefs are never overwritten; each change produces a BeliefRevision
    that points to the previous version, forming an auditable history.

    Attributes:
        belief_id:      ID of the belief being revised.
        previous_state: Serialized snapshot of the belief before revision.
        new_state:      Serialized snapshot of the belief after revision.
        evidence_id:    ID of the evidence that triggered the revision.
        reason:         Human-readable explanation of the revision.
        revised_at:     UTC timestamp of the revision.
        id:             Unique identifier (auto-generated if not provided).
    """

    belief_id: str
    previous_state: dict
    new_state: dict
    evidence_id: str
    reason: str
    revised_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str | None = field(default=None)

    def __post_init__(self) -> None:
        if self.id is None:
            payload = json.dumps(
                {
                    "belief_id": self.belief_id,
                    "evidence_id": self.evidence_id,
                    "revised_at": self.revised_at.isoformat(),
                },
                sort_keys=True,
            )
            self.id = hashlib.sha256(payload.encode()).hexdigest()[:16]
