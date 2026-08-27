"""
Tests for the EpistemicCore rule engine.

Validates:
  - Belief typing enforcement
  - Confidence bound validation
  - Update eligibility (evidence required, reliability threshold, delta cap)
  - Adversarial pressure rejection
  - Belief state resolution
"""

import pytest

from episteme.core import EpistemicCore
from episteme.models import Belief, BeliefState, BeliefType, Evidence


def make_belief(
    statement: str = "The Earth orbits the Sun.",
    btype: BeliefType = BeliefType.FACT,
    confidence: float = 0.8,
    domain: str = "astronomy",
    evidence_ids: list[str] | None = None,
    counter_evidence_ids: list[str] | None = None,
    state: BeliefState = BeliefState.ACTIVE,
) -> Belief:
    return Belief(
        statement=statement,
        type=btype,
        confidence=confidence,
        domain=domain,
        evidence_ids=evidence_ids or [],
        counter_evidence_ids=counter_evidence_ids or [],
        state=state,
    )


def make_evidence(
    summary: str = "Observation confirms orbit.",
    reliability: float = 0.9,
    context_hash: str = "ctx001",
) -> Evidence:
    return Evidence(summary=summary, reliability=reliability, context_hash=context_hash)


class TestEpistemicCoreValidation:
    def test_validate_belief_valid(self):
        core = EpistemicCore()
        core.validate_belief(make_belief())  # should not raise

    def test_validate_belief_empty_statement(self):
        core = EpistemicCore()
        b = make_belief(statement="   ")
        with pytest.raises(ValueError, match="statement"):
            core.validate_belief(b)

    def test_validate_belief_empty_domain(self):
        core = EpistemicCore()
        b = make_belief(domain="  ")
        with pytest.raises(ValueError, match="domain"):
            core.validate_belief(b)

    def test_validate_evidence_valid(self):
        core = EpistemicCore()
        core.validate_evidence(make_evidence())  # should not raise

    def test_validate_evidence_empty_summary(self):
        core = EpistemicCore()
        e = make_evidence(summary="  ")
        with pytest.raises(ValueError, match="summary"):
            core.validate_evidence(e)

    def test_validate_evidence_empty_context_hash(self):
        core = EpistemicCore()
        e = make_evidence(context_hash="  ")
        with pytest.raises(ValueError, match="context_hash"):
            core.validate_evidence(e)


class TestUpdateEligibility:
    def setup_method(self):
        self.core = EpistemicCore(reliability_threshold=0.5)

    def test_eligible_update(self):
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.8)
        decision = self.core.evaluate_update(b, e, proposed_confidence=0.7)
        assert decision.eligible is True

    def test_ineligible_duplicate_evidence(self):
        e = make_evidence()
        b = make_belief(evidence_ids=[e.id])
        decision = self.core.evaluate_update(b, e, proposed_confidence=0.9)
        assert decision.eligible is False
        assert "already been applied" in decision.reason

    def test_ineligible_low_reliability(self):
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.2)
        decision = self.core.evaluate_update(b, e, proposed_confidence=0.8)
        assert decision.eligible is False
        assert "below the required threshold" in decision.reason

    def test_threshold_boundary_exactly_equal(self):
        """Reliability exactly at threshold should be eligible."""
        core = EpistemicCore(reliability_threshold=0.5)
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.5)
        decision = core.evaluate_update(b, e, proposed_confidence=0.6)
        assert decision.eligible is True

    def test_confidence_delta_clamped(self):
        """Large confidence jumps are clamped to max_confidence_delta."""
        core = EpistemicCore(max_confidence_delta=0.1)
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.9)
        decision = core.evaluate_update(b, e, proposed_confidence=0.99)
        assert decision.eligible is True
        assert decision.suggested_confidence == pytest.approx(0.6, abs=1e-9)

    def test_out_of_range_proposed_confidence_rejected(self):
        """A proposal outside [0, 1] is refused outright, never clamped into range."""
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.9)
        for garbage in (1.9, -5.0):
            decision = self.core.evaluate_update(b, e, proposed_confidence=garbage)
            assert decision.eligible is False
            assert "outside [0, 1]" in decision.reason

    def test_evidence_already_counter_cannot_support(self):
        """One evidence record cannot stand on both sides of a belief."""
        e = make_evidence()
        b = make_belief(counter_evidence_ids=[e.id])
        decision = self.core.evaluate_update(b, e, proposed_confidence=0.9)
        assert decision.eligible is False
        assert "counter-evidence" in decision.reason

    def test_language_only_update_rejected(self):
        """Updates driven purely by language/repetition must be blocked."""
        core = EpistemicCore()
        decision = core.check_adversarial_pressure(
            ["everyone says this is true", "consensus"]
        )
        assert decision.eligible is False
        assert "repetition" in decision.reason.lower() or "language" in decision.reason.lower()

    def test_evidence_based_update_not_rejected(self):
        core = EpistemicCore()
        decision = core.check_adversarial_pressure(
            ["new observation data supports the claim"]
        )
        assert decision.eligible is True

    def test_authority_appeal_rejected(self):
        core = EpistemicCore()
        decision = core.check_adversarial_pressure(["authority says it is so"])
        assert decision.eligible is False

    def test_mixed_social_proof_and_evidence_not_rejected(self):
        """Even if social proof is present, evidence keywords rescue the update."""
        core = EpistemicCore()
        decision = core.check_adversarial_pressure(
            ["consensus agrees and new evidence from observations confirms it"]
        )
        assert decision.eligible is True


class TestCounterEvidence:
    def setup_method(self):
        self.core = EpistemicCore(reliability_threshold=0.5)

    def test_eligible_counter_evidence(self):
        b = make_belief()
        e = make_evidence(reliability=0.7, context_hash="ctx_counter")
        decision = self.core.evaluate_counter_evidence(b, e)
        assert decision.eligible is True

    def test_duplicate_counter_evidence_rejected(self):
        e = make_evidence(reliability=0.7, context_hash="ctx_counter")
        b = make_belief(counter_evidence_ids=[e.id])
        decision = self.core.evaluate_counter_evidence(b, e)
        assert decision.eligible is False
        assert "already recorded" in decision.reason

    def test_low_reliability_counter_evidence_rejected(self):
        b = make_belief()
        e = make_evidence(reliability=0.3, context_hash="ctx_counter")
        decision = self.core.evaluate_counter_evidence(b, e)
        assert decision.eligible is False

    def test_supporting_evidence_cannot_dispute(self):
        """The mirror of the evaluate_update cross-check: evidence recorded
        as supporting cannot also be recorded against the same belief."""
        e = make_evidence(reliability=0.7, context_hash="ctx_counter")
        b = make_belief(evidence_ids=[e.id])
        decision = self.core.evaluate_counter_evidence(b, e)
        assert decision.eligible is False
        assert "supporting" in decision.reason


class TestCoreConstruction:
    def test_invalid_reliability_threshold_rejected(self):
        for bad in (-0.1, 1.5):
            with pytest.raises(ValueError, match="reliability_threshold"):
                EpistemicCore(reliability_threshold=bad)

    def test_invalid_max_confidence_delta_rejected(self):
        """A delta cap outside [0, 1] would turn no-op updates into jumps."""
        for bad in (-1.0, 1.5):
            with pytest.raises(ValueError, match="max_confidence_delta"):
                EpistemicCore(0.5, bad)


class TestBeliefStateResolution:
    def setup_method(self):
        self.core = EpistemicCore()
        self.belief = make_belief()

    def test_no_evidence_yields_unknown(self):
        state = self.core.resolve_state(self.belief, False, False)
        assert state == BeliefState.UNKNOWN

    def test_supporting_only_yields_active(self):
        state = self.core.resolve_state(self.belief, True, False)
        assert state == BeliefState.ACTIVE

    def test_counter_only_yields_undecided(self):
        state = self.core.resolve_state(self.belief, False, True)
        assert state == BeliefState.UNDECIDED

    def test_both_yields_disputed(self):
        state = self.core.resolve_state(self.belief, True, True)
        assert state == BeliefState.DISPUTED


class TestConfidenceComputation:
    def test_compute_revised_confidence_increases(self):
        core = EpistemicCore()
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.8)
        new_conf = core.compute_revised_confidence(b, e)
        assert new_conf > b.confidence

    def test_compute_revised_confidence_capped_at_one(self):
        core = EpistemicCore()
        b = make_belief(confidence=0.99)
        e = make_evidence(reliability=1.0)
        new_conf = core.compute_revised_confidence(b, e)
        assert new_conf <= 1.0

    def test_custom_reliability_threshold(self):
        core = EpistemicCore(reliability_threshold=0.9)
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.85)
        decision = core.evaluate_update(b, e, proposed_confidence=0.7)
        assert decision.eligible is False
