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


#: Weight of the prior a new belief starts from, in pseudo-observations
#: (ADR-0005). A belief created at confidence ``c`` starts from
#: Beta(2c, 2(1 - c)), so 0.5 is the uniform Beta(1, 1). The value is a
#: design choice (THEORY), not a calibrated constant.
PRIOR_STRENGTH = 2.0

# Tolerance for checking that a stored confidence is the mean of its counts.
_CONFIDENCE_TOLERANCE = 1e-9


@dataclass
class Belief:
    """
    An explicit, typed belief object with confidence and evidence references.

    Confidence is the mean of a Beta(alpha, beta) posterior (ADR-0005):
    ``alpha`` accumulates the reliability of supporting evidence and
    ``beta`` that of counter-evidence, on top of a prior worth
    ``PRIOR_STRENGTH`` observations. ``confidence`` is derived from the
    counts, never set apart from them.

    Attributes:
        statement:            The belief statement.
        type:                 Belief type (FACT / THEORY / OPINION / FICTION).
        confidence:           Confidence score in [0, 1]; for a new belief it
                              sets the prior, afterwards it must equal
                              ``alpha / (alpha + beta)``.
        domain:               Semantic domain the belief belongs to.
        evidence_ids:         IDs of supporting evidence.
        counter_evidence_ids: IDs of contradicting evidence.
        state:                Lifecycle state.
        id:                   Unique identifier (auto-generated if not provided).
        created_at:           UTC timestamp of initial creation.
        alpha:                Supporting weight, prior included. Derived from
                              ``confidence`` when both counts are omitted.
        beta:                 Contradicting weight, prior included.
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
    alpha: float | None = field(default=None)
    beta: float | None = field(default=None)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Belief confidence must be in [0, 1], got {self.confidence}"
            )
        if self.alpha is None and self.beta is None:
            self.alpha = PRIOR_STRENGTH * self.confidence
            self.beta = PRIOR_STRENGTH * (1.0 - self.confidence)
        elif self.alpha is None or self.beta is None:
            raise ValueError("Belief alpha and beta must be given together or not at all.")
        else:
            self.confidence = belief_confidence(self.alpha, self.beta, self.confidence)
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

    @property
    def evidence_weight(self) -> float:
        """Reliability-weighted evidence recorded beyond the prior, both sides.

        Two beliefs at the same confidence can rest on very different amounts
        of evidence; this is the amount (ADR-0005).
        """
        if self.alpha is None or self.beta is None:
            # __post_init__ always sets both; only a mutated object lacks them.
            raise ValueError(f"Belief {self.id!r} has no alpha/beta counts.")
        return self.alpha + self.beta - PRIOR_STRENGTH


def belief_confidence(alpha: float, beta: float, stated: float | None = None) -> float:
    """Return the Beta mean ``alpha / (alpha + beta)``, checking the counts.

    If *stated* is given it must already equal that mean: confidence is
    derived from the counts and cannot be asserted apart from them.

    Raises
    ------
    ValueError
        If either count is negative, both are zero, or *stated* disagrees.
    """
    if alpha < 0.0 or beta < 0.0 or alpha + beta <= 0.0:
        raise ValueError(
            f"Belief alpha and beta must be non-negative and not both zero, "
            f"got alpha={alpha}, beta={beta}"
        )
    mean = alpha / (alpha + beta)
    if stated is not None and abs(stated - mean) > _CONFIDENCE_TOLERANCE:
        raise ValueError(
            f"Belief confidence {stated} is not the mean {mean} of alpha={alpha}, "
            f"beta={beta}; confidence is derived from the counts (ADR-0005)."
        )
    return mean


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
