"""
EPISTEME Experience Loop

Observes outcomes, constructs Evidence objects, and triggers belief
revision through the Epistemic Core and Epistemic Memory.

Design (spec §1.4.4):
  - Observations come from tool results, execution outputs, or feedback.
  - Each observation may generate one or more Evidence objects.
  - Evidence is validated by EpistemicCore before being applied.
  - The loop fails loudly on unimplemented or ambiguous outcomes (spec §1.7).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from episteme.core import EpistemicCore
from episteme.memory import EpistemicMemory
from episteme.models import Belief, Evidence


@dataclass
class Observation:
    """
    A raw outcome observed from the environment.

    Attributes:
        content:      Free-form text describing the observation.
        source:       Origin of the observation (tool name, user, etc.).
        reliability:  Estimated reliability of the source in [0, 1].
        domain:       Semantic domain relevant to this observation.
        metadata:     Optional key/value metadata.
    """

    content: str
    source: str
    reliability: float
    domain: str = "general"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.reliability <= 1.0:
            raise ValueError(
                f"Observation reliability must be in [0, 1], got {self.reliability}"
            )


@dataclass
class RevisionResult:
    """
    Summary of a belief revision attempt triggered by an observation.

    Attributes:
        belief_id:    ID of the belief that was (or was not) revised.
        revised:      Whether the revision was actually applied.
        reason:       Explanation from the core.
        evidence_id:  ID of the evidence used (if applicable).
    """

    belief_id: str
    revised: bool
    reason: str
    evidence_id: str | None = None


class ExperienceLoop:
    """
    Connects environment observations to belief revision.

    Parameters
    ----------
    core:
        The EpistemicCore to use for update eligibility decisions.
    memory:
        The EpistemicMemory to read and revise beliefs.
    on_revision:
        Optional callback invoked with the revised Belief after each
        successful revision.  Useful for logging or side-effects.
    """

    def __init__(
        self,
        core: EpistemicCore,
        memory: EpistemicMemory,
        on_revision: Callable[[Belief], None] | None = None,
    ) -> None:
        self._core = core
        self._memory = memory
        self._on_revision = on_revision

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(
        self,
        observation: Observation,
        belief_ids: list[str],
        *,
        supporting: bool = True,
    ) -> list[RevisionResult]:
        """
        Process an *observation* and attempt to revise each listed belief.

        Parameters
        ----------
        observation:
            The environmental outcome to process.
        belief_ids:
            List of belief IDs that may be affected by this observation.
        supporting:
            If True, the observation supports the listed beliefs.
            If False, it is treated as counter-evidence.

        Returns
        -------
        list[RevisionResult]
            One result per belief id.
        """
        evidence = self._build_evidence(observation)
        self._memory.add_evidence(evidence)

        results = []
        for bid in belief_ids:
            result = self._apply_to_belief(evidence, bid, supporting=supporting)
            results.append(result)
        return results

    def observe_outcome(
        self,
        content: str,
        source: str,
        reliability: float,
        belief_ids: list[str],
        *,
        domain: str = "general",
        supporting: bool = True,
        metadata: dict | None = None,
    ) -> list[RevisionResult]:
        """
        Convenience wrapper for ``observe()`` with keyword arguments.
        """
        obs = Observation(
            content=content,
            source=source,
            reliability=reliability,
            domain=domain,
            metadata=metadata or {},
        )
        return self.observe(obs, belief_ids, supporting=supporting)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_evidence(self, observation: Observation) -> Evidence:
        """Convert an Observation into an Evidence object, deduplicating by context_hash."""
        context_payload = json.dumps(
            {"content": observation.content, "source": observation.source},
            sort_keys=True,
        )
        context_hash = hashlib.sha256(context_payload.encode()).hexdigest()[:32]

        # Reuse existing evidence with the same context to enable duplicate detection
        existing = self._memory.get_evidence_by_context_hash(context_hash)
        if existing is not None:
            return existing

        return Evidence(
            summary=f"[{observation.source}] {observation.content}",
            reliability=observation.reliability,
            context_hash=context_hash,
            timestamp=datetime.now(UTC),
        )

    def _apply_to_belief(
        self,
        evidence: Evidence,
        belief_id: str,
        *,
        supporting: bool,
    ) -> RevisionResult:
        """
        Attempt to apply *evidence* to the belief identified by *belief_id*.

        For supporting evidence: evaluate update eligibility and revise if
        eligible.
        For counter-evidence: evaluate counter-evidence eligibility and mark
        the belief DISPUTED if eligible.
        """
        belief = self._memory.get_belief(belief_id)
        if belief is None:
            return RevisionResult(
                belief_id=belief_id,
                revised=False,
                reason=f"Belief {belief_id!r} not found in memory.",
                evidence_id=evidence.id,
            )

        if supporting:
            new_conf = self._core.compute_revised_confidence(belief, evidence)
            decision = self._core.evaluate_update(belief, evidence, new_conf)

            if not decision.eligible:
                return RevisionResult(
                    belief_id=belief_id,
                    revised=False,
                    reason=decision.reason,
                    evidence_id=evidence.id,
                )

            final_conf = (
                decision.suggested_confidence
                if decision.suggested_confidence is not None
                else new_conf
            )

            new_evidence_ids = list(belief.evidence_ids) + [evidence.id]
            has_counter = len(belief.counter_evidence_ids) > 0
            new_state = self._core.resolve_state(
                belief, has_supporting=True, has_counter=has_counter
            )

            self._memory.revise_belief(
                belief_id,
                evidence,
                new_confidence=final_conf,
                new_state=new_state,
                new_evidence_ids=new_evidence_ids,
                reason=decision.reason,
            )

            updated_belief = self._memory.get_belief(belief_id)
            if updated_belief is not None and self._on_revision:
                self._on_revision(updated_belief)

            return RevisionResult(
                belief_id=belief_id,
                revised=True,
                reason=decision.reason,
                evidence_id=evidence.id,
            )

        # Counter-evidence path
        decision = self._core.evaluate_counter_evidence(belief, evidence)
        if not decision.eligible:
            return RevisionResult(
                belief_id=belief_id,
                revised=False,
                reason=decision.reason,
                evidence_id=evidence.id,
            )

        new_counter_ids = list(belief.counter_evidence_ids) + [evidence.id]
        has_supporting = len(belief.evidence_ids) > 0
        new_state = self._core.resolve_state(
            belief, has_supporting=has_supporting, has_counter=True
        )

        self._memory.revise_belief(
            belief_id,
            evidence,
            new_state=new_state,
            new_counter_evidence_ids=new_counter_ids,
            reason=decision.reason,
        )

        updated_belief = self._memory.get_belief(belief_id)
        if updated_belief is not None and self._on_revision:
            self._on_revision(updated_belief)

        return RevisionResult(
            belief_id=belief_id,
            revised=True,
            reason=decision.reason,
            evidence_id=evidence.id,
        )
