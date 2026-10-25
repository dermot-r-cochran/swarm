"""
Tests for the EpistemicCore rule engine.

Validates:
  - Belief typing enforcement
  - Confidence bound validation
  - Update eligibility (evidence required, reliability threshold, delta cap)
  - Adversarial pressure rejection
  - Belief state resolution
  - The module has no import path to storage at all (ADR-0001)
"""

import ast
from pathlib import Path
from typing import ClassVar

import pytest

import episteme.core
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

    def test_validate_belief_rejects_mutated_type_and_confidence(self):
        """The dataclasses validate at construction, so validate_belief's own
        checks matter for objects mutated afterwards."""
        core = EpistemicCore()
        b = make_belief()
        b.type = 123
        with pytest.raises(ValueError, match="belief type"):
            core.validate_belief(b)
        b = make_belief()
        b.confidence = 5.0
        with pytest.raises(ValueError, match="Confidence"):
            core.validate_belief(b)

    def test_validate_evidence_rejects_mutated_reliability(self):
        core = EpistemicCore()
        e = Evidence(summary="ok", reliability=0.9, context_hash="ctx")
        e.reliability = -1.0
        with pytest.raises(ValueError, match="reliability"):
            core.validate_evidence(e)

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
    def test_reliability_threshold_property_reflects_construction(self):
        assert EpistemicCore(reliability_threshold=0.7).reliability_threshold == 0.7

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


class TestSideEffectFree:
    """
    ADR-0001 as a structural property rather than a reading of the code.

    The tests above exercise the core's decisions, and ``test_public_api.py``
    asserts the documented contract that it never raises; neither would
    notice a method that quietly persisted its decision. What makes the
    decision hold is that ``episteme.core`` has nothing to write *through*:
    it imports only ``episteme.models``. Assert that directly, the same way
    ``test_interface.py`` guards ADR-0003 and ``test_population.py`` guards
    ADR-0004, so the invariant fails the moment a storage import appears,
    whatever the method is called.

    ``sqlite3`` is forbidden as well as the package's own storage modules
    because it is the one route to disk the package already uses, and the
    obvious one to reach for without going through ``EpistemicMemory``.
    ``episteme.experience`` is forbidden because it imports memory, so an
    import of it would be a write path at one remove.
    """

    FORBIDDEN: ClassVar[set[str]] = {"episteme.memory", "episteme.experience", "sqlite3"}

    @staticmethod
    def _imported_modules(module) -> set[str]:
        """Every module named by an import in *module*, at any nesting depth.

        Walks the AST rather than inspecting the imported module object, so
        a deferred import inside a function body is caught too.
        """
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    def test_core_does_not_import_storage(self):
        imported = self._imported_modules(episteme.core)
        breaches = imported & self.FORBIDDEN
        assert not breaches, (
            "episteme.core must have no import path to storage (ADR-0001), "
            f"but imports: {sorted(breaches)}. The core evaluates and returns "
            "an UpdateDecision; callers orchestrate writes through "
            "EpistemicMemory afterwards."
        )


class TestBetaPosterior:
    """ADR-0005: the Beta update, symmetric for and against, delta-capped."""

    def test_supporting_evidence_adds_its_reliability_to_alpha(self):
        core = EpistemicCore()
        b = make_belief(confidence=0.5)
        alpha, beta = core.compute_posterior(b, make_evidence(reliability=0.6), supporting=True)
        assert (alpha, beta) == pytest.approx((1.6, 1.0))

    def test_counter_evidence_adds_its_reliability_to_beta_and_lowers_confidence(self):
        core = EpistemicCore()
        b = make_belief(confidence=0.5)
        alpha, beta = core.compute_posterior(b, make_evidence(reliability=0.6), supporting=False)
        assert (alpha, beta) == pytest.approx((1.0, 1.6))
        assert alpha / (alpha + beta) < b.confidence

    @pytest.mark.parametrize("supporting", [True, False])
    @pytest.mark.parametrize("confidence", [0.0, 0.05, 0.3, 0.5, 0.7, 0.95, 1.0])
    @pytest.mark.parametrize("reliability", [0.5, 0.8, 1.0])
    def test_one_record_never_moves_confidence_beyond_the_cap(
        self, supporting, confidence, reliability
    ):
        core = EpistemicCore(max_confidence_delta=0.1)
        b = make_belief(confidence=confidence)
        alpha, beta = core.compute_posterior(
            b, make_evidence(reliability=reliability), supporting=supporting
        )
        assert abs(alpha / (alpha + beta) - b.confidence) <= 0.1 + 1e-12

    def test_cap_reduces_the_weight_rather_than_the_mean_alone(self):
        # At confidence 0 a fully reliable record would move the mean by a
        # third; with a 0.1 cap the weight shrinks so counts and mean agree.
        core = EpistemicCore(max_confidence_delta=0.1)
        b = make_belief(confidence=0.0)
        alpha, beta = core.compute_posterior(b, make_evidence(reliability=1.0), supporting=True)
        assert alpha < 1.0
        assert alpha / (alpha + beta) == pytest.approx(0.1)

    def test_compute_revised_confidence_is_the_supporting_posterior_mean(self):
        core = EpistemicCore()
        b = make_belief(confidence=0.5)
        e = make_evidence(reliability=0.6)
        alpha, beta = core.compute_posterior(b, e, supporting=True)
        assert core.compute_revised_confidence(b, e) == pytest.approx(alpha / (alpha + beta))

    def test_belief_without_counts_fails_loudly(self):
        core = EpistemicCore()
        b = make_belief()
        b.beta = None
        with pytest.raises(ValueError, match="no alpha/beta"):
            core.compute_posterior(b, make_evidence(), supporting=True)
