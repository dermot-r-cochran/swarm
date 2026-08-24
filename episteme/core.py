"""
EPISTEME Epistemic Core

Immutable ruleset that governs:
  - Belief typing enforcement
  - Confidence bound validation
  - Update eligibility determination

The core is intentionally side-effect-free.  It accepts data, applies
rules, and returns decisions—it never writes to storage.  All callers
must consult the core before modifying beliefs.

Design invariants (per spec §1.6):
  1. Beliefs update ONLY if new evidence is present.
  2. Evidence reliability must meet or exceed the configured threshold.
  3. Every update is logged and reversible.
  4. Language, repetition, consensus, or confidence alone are insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass

from episteme.models import Belief, BeliefState, BeliefType, Evidence


class UpdateEligibilityError(Exception):
    """Raised when a belief update is rejected by the epistemic core."""


@dataclass(frozen=True)
class UpdateDecision:
    """Result returned by the core after evaluating an update request."""

    eligible: bool
    reason: str
    suggested_confidence: float | None = None


class EpistemicCore:
    """
    Immutable epistemic rule engine.

    Parameters
    ----------
    reliability_threshold:
        Minimum evidence reliability required for a belief update.
        Defaults to 0.5 (per spec §1.6).
    max_confidence_delta:
        Maximum allowed change in confidence per revision.
        Prevents runaway confidence inflation.
    """

    DEFAULT_RELIABILITY_THRESHOLD = 0.5

    def __init__(
        self,
        reliability_threshold: float = DEFAULT_RELIABILITY_THRESHOLD,
        max_confidence_delta: float = 0.3,
    ) -> None:
        if not 0.0 <= reliability_threshold <= 1.0:
            raise ValueError(
                f"reliability_threshold must be in [0, 1], got {reliability_threshold}"
            )
        self._reliability_threshold = reliability_threshold
        self._max_confidence_delta = max_confidence_delta

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def reliability_threshold(self) -> float:
        return self._reliability_threshold

    def validate_belief(self, belief: Belief) -> None:
        """
        Assert that a belief object is structurally valid.

        Raises
        ------
        ValueError
            If any invariant is violated.
        """
        # ValueError, not TypeError, is the documented contract (see the
        # docstring above) and what callers already catch - changing the
        # raised type is an API change, not a lint fix.
        if not isinstance(belief.type, BeliefType):
            raise ValueError(f"Unknown belief type: {belief.type!r}")  # noqa: TRY004
        if not 0.0 <= belief.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be in [0, 1], got {belief.confidence}"
            )
        if not belief.statement.strip():
            raise ValueError("Belief statement must not be empty.")
        if not belief.domain.strip():
            raise ValueError("Belief domain must not be empty.")

    def validate_evidence(self, evidence: Evidence) -> None:
        """
        Assert that an evidence object is structurally valid.

        Raises
        ------
        ValueError
            If any invariant is violated.
        """
        if not 0.0 <= evidence.reliability <= 1.0:
            raise ValueError(
                f"Evidence reliability must be in [0, 1], got {evidence.reliability}"
            )
        if not evidence.summary.strip():
            raise ValueError("Evidence summary must not be empty.")
        if not evidence.context_hash.strip():
            raise ValueError("Evidence context_hash must not be empty.")

    def evaluate_update(
        self,
        belief: Belief,
        evidence: Evidence,
        proposed_confidence: float,
    ) -> UpdateDecision:
        """
        Decide whether *belief* may be revised given *evidence*.

        Implements the update rules from spec §1.6:
          1. New evidence must be present (evidence not already in belief).
          2. Evidence reliability ≥ threshold.
          3. Proposed confidence change ≤ max_confidence_delta.

        Returns
        -------
        UpdateDecision
            `eligible=True` if the update is allowed; `False` otherwise
            with a human-readable reason.
        """
        # Rule 1 – evidence must be genuinely new
        if evidence.id in belief.evidence_ids:
            return UpdateDecision(
                eligible=False,
                reason=(
                    f"Evidence {evidence.id!r} has already been applied to "
                    f"belief {belief.id!r}."
                ),
            )

        # Rule 2 – reliability must meet threshold
        if evidence.reliability < self._reliability_threshold:
            return UpdateDecision(
                eligible=False,
                reason=(
                    f"Evidence reliability {evidence.reliability:.3f} is below "
                    f"the required threshold {self._reliability_threshold:.3f}."
                ),
            )

        # Rule 3 – confidence delta must be within bounds
        delta = abs(proposed_confidence - belief.confidence)
        if delta > self._max_confidence_delta:
            # Clamp to allowed range and still permit the update
            direction = 1 if proposed_confidence > belief.confidence else -1
            clamped = belief.confidence + direction * self._max_confidence_delta
            clamped = max(0.0, min(1.0, clamped))
            return UpdateDecision(
                eligible=True,
                reason=(
                    f"Confidence delta {delta:.3f} exceeds max allowed "
                    f"{self._max_confidence_delta:.3f}; clamped to {clamped:.3f}."
                ),
                suggested_confidence=clamped,
            )

        # Validate proposed confidence range
        if not 0.0 <= proposed_confidence <= 1.0:
            return UpdateDecision(
                eligible=False,
                reason=(
                    f"Proposed confidence {proposed_confidence} is outside [0, 1]."
                ),
            )

        return UpdateDecision(
            eligible=True,
            reason="Update meets all epistemic criteria.",
            suggested_confidence=proposed_confidence,
        )

    def evaluate_counter_evidence(
        self,
        belief: Belief,
        counter_evidence: Evidence,
    ) -> UpdateDecision:
        """
        Evaluate whether counter-evidence is strong enough to dispute a belief.

        When counter-evidence meets the threshold the belief transitions to
        DISPUTED state (per spec §1.7 – Dispute → persisted disagreement).
        """
        if counter_evidence.id in belief.counter_evidence_ids:
            return UpdateDecision(
                eligible=False,
                reason=(
                    f"Counter-evidence {counter_evidence.id!r} already recorded "
                    f"for belief {belief.id!r}."
                ),
            )

        if counter_evidence.reliability < self._reliability_threshold:
            return UpdateDecision(
                eligible=False,
                reason=(
                    f"Counter-evidence reliability {counter_evidence.reliability:.3f} "
                    f"is below threshold {self._reliability_threshold:.3f}."
                ),
            )

        return UpdateDecision(
            eligible=True,
            reason="Counter-evidence meets threshold; belief should be disputed.",
        )

    def compute_revised_confidence(
        self,
        belief: Belief,
        evidence: Evidence,
    ) -> float:
        """
        Compute a new confidence value after applying *evidence*.

        Uses a simple Bayesian-inspired update:
          new_confidence = old + evidence.reliability * (1 - old)   if supporting
          new_confidence = old * (1 - evidence.reliability)          if opposing

        The caller is responsible for determining the direction of evidence.
        This helper treats the evidence as *supporting*.
        """
        new_conf = belief.confidence + evidence.reliability * (1.0 - belief.confidence)
        return min(1.0, max(0.0, new_conf))

    def check_adversarial_pressure(
        self,
        update_reasons: list[str],
    ) -> UpdateDecision:
        """
        Guard against language-only or social-proof attacks (spec §1.6).

        Rejects updates whose justification is composed entirely of
        inadmissible reasons (repetition, authority appeal, consensus).

        Parameters
        ----------
        update_reasons:
            List of reasons provided for the update (e.g., from an LLM).
        """
        inadmissible_keywords = {
            "everyone says",
            "consensus",
            "authority",
            "repeated",
            "repetition",
            "popular",
            "because i said",
            "trust me",
        }
        reasons_text = " ".join(update_reasons).lower()
        if any(kw in reasons_text for kw in inadmissible_keywords) and not any(
            admissible in reasons_text
            for admissible in ("evidence", "observation", "data", "result")
        ):
            return UpdateDecision(
                eligible=False,
                reason=(
                    "Update rejected: justification relies solely on "
                    "language, repetition, or consensus—not evidence."
                ),
            )
        return UpdateDecision(
            eligible=True,
            reason="Update reasons appear evidence-based.",
        )

    # ------------------------------------------------------------------
    # Belief state transitions
    # ------------------------------------------------------------------

    def resolve_state(
        self,
        belief: Belief,
        has_supporting: bool,
        has_counter: bool,
    ) -> BeliefState:
        """
        Determine the correct BeliefState given evidence availability.

        Per spec §1.7:
          - Unknown   → UNKNOWN
          - Dispute   → DISPUTED
          - Ambiguity → UNDECIDED
        """
        if not has_supporting and not has_counter:
            return BeliefState.UNKNOWN
        if has_supporting and has_counter:
            return BeliefState.DISPUTED
        if has_supporting:
            return BeliefState.ACTIVE
        # has_counter only
        return BeliefState.UNDECIDED
