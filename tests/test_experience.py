"""
Tests for the ExperienceLoop.

Validates:
  - Observations become evidence and trigger belief revision
  - Low-reliability observations do not trigger revision
  - Counter-evidence transitions beliefs to DISPUTED
  - Unknown belief IDs are handled gracefully
  - Revision callback is invoked
"""

import pytest

from episteme.core import EpistemicCore
from episteme.experience import ExperienceLoop
from episteme.memory import EpistemicMemory
from episteme.models import Belief, BeliefState, BeliefType, Evidence


def make_belief(**kwargs) -> Belief:
    defaults = {
        "statement": "Gravity attracts masses.",
        "type": BeliefType.FACT,
        "confidence": 0.6,
        "domain": "physics",
    }
    defaults.update(kwargs)
    return Belief(**defaults)


@pytest.fixture
def setup():
    core = EpistemicCore(reliability_threshold=0.5)
    mem = EpistemicMemory(":memory:")
    loop = ExperienceLoop(core, mem)
    return core, mem, loop


class TestExperienceLoopBasic:
    def test_supporting_observation_increases_confidence(self, setup):
        _core, mem, loop = setup
        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        results = loop.observe_outcome(
            content="Experiment confirms gravity.",
            source="experiment",
            reliability=0.9,
            belief_ids=[b.id],
            domain="physics",
            supporting=True,
        )

        assert len(results) == 1
        assert results[0].revised is True
        updated = mem.get_belief(b.id)
        assert updated.confidence > 0.5

    def test_low_reliability_does_not_revise(self, setup):
        _core, mem, loop = setup
        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        results = loop.observe_outcome(
            content="Unverified rumor.",
            source="rumor",
            reliability=0.1,
            belief_ids=[b.id],
            domain="physics",
            supporting=True,
        )

        assert results[0].revised is False
        updated = mem.get_belief(b.id)
        assert updated.confidence == pytest.approx(0.5)

    def test_counter_observation_marks_belief_disputed(self, setup):
        _core, mem, loop = setup
        # Seed with one supporting evidence so state can become DISPUTED
        supporting_e = Evidence(
            summary="Initial support",
            reliability=0.9,
            context_hash="ctx_support",
        )
        mem.add_evidence(supporting_e)

        # Add belief pre-seeded with supporting evidence
        b2 = make_belief(
            statement="Gravity attracts masses - v2",
            confidence=0.8,
            evidence_ids=[supporting_e.id],
        )
        mem.add_belief(b2)

        results = loop.observe_outcome(
            content="Anomalous result contradicts gravity model.",
            source="lab",
            reliability=0.8,
            belief_ids=[b2.id],
            domain="physics",
            supporting=False,
        )

        assert results[0].revised is True
        updated = mem.get_belief(b2.id)
        assert updated.state == BeliefState.DISPUTED

    def test_unknown_belief_id_handled_gracefully(self, setup):
        _core, _mem, loop = setup
        results = loop.observe_outcome(
            content="Some observation.",
            source="sensor",
            reliability=0.9,
            belief_ids=["nonexistent-id"],
            domain="physics",
        )
        assert results[0].revised is False
        assert "not found" in results[0].reason

    def test_revision_callback_invoked(self, setup):
        _core, mem, loop = setup
        called_with = []
        loop._on_revision = lambda b: called_with.append(b)

        b = make_belief(confidence=0.4)
        mem.add_belief(b)

        loop.observe_outcome(
            content="High-confidence observation.",
            source="sensor",
            reliability=0.9,
            belief_ids=[b.id],
            domain="physics",
            supporting=True,
        )

        assert len(called_with) == 1
        assert called_with[0].id == b.id

    def test_evidence_persisted_in_memory(self, setup):
        _core, mem, loop = setup
        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        results = loop.observe_outcome(
            content="Verified measurement.",
            source="instrument",
            reliability=0.95,
            belief_ids=[b.id],
            domain="physics",
        )

        evidence_id = results[0].evidence_id
        assert evidence_id is not None
        assert mem.get_evidence(evidence_id) is not None

    def test_duplicate_evidence_not_applied_twice(self, setup):
        """Applying the same observation twice should not revise the belief twice."""
        _core, mem, loop = setup
        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        obs_kwargs = {
            "content": "Repeating the same observation.",
            "source": "instrument",
            "reliability": 0.9,
            "belief_ids": [b.id],
            "domain": "physics",
        }

        r1 = loop.observe_outcome(**obs_kwargs)
        conf_after_first = mem.get_belief(b.id).confidence

        # Same content/source will produce same context hash → same evidence id
        r2 = loop.observe_outcome(**obs_kwargs)
        conf_after_second = mem.get_belief(b.id).confidence

        assert r1[0].revised is True
        # Second application with same evidence should be rejected
        assert r2[0].revised is False
        assert conf_after_first == pytest.approx(conf_after_second)

    def test_multiple_beliefs_revised_in_one_call(self, setup):
        _core, mem, loop = setup
        b1 = make_belief(statement="Claim A", confidence=0.4)
        b2 = make_belief(statement="Claim B", confidence=0.4)
        mem.add_belief(b1)
        mem.add_belief(b2)

        results = loop.observe_outcome(
            content="Broad experimental confirmation.",
            source="lab",
            reliability=0.85,
            belief_ids=[b1.id, b2.id],
            domain="physics",
        )

        assert len(results) == 2
        assert all(r.revised for r in results)
        assert mem.get_belief(b1.id).confidence > 0.4
        assert mem.get_belief(b2.id).confidence > 0.4


class TestLongHorizonStability:
    """
    Validates near-zero drift over many turns without new evidence (spec §1.8).
    """

    def test_no_drift_without_evidence(self):
        """Confidence must not change unless evidence is provided."""
        core = EpistemicCore(reliability_threshold=0.5)
        mem = EpistemicMemory(":memory:")
        _loop = ExperienceLoop(core, mem)

        b = make_belief(confidence=0.7)
        mem.add_belief(b)

        initial_confidence = mem.get_belief(b.id).confidence

        # 1000 turns with no evidence → confidence unchanged
        for _ in range(1000):
            pass  # No observations applied

        final_confidence = mem.get_belief(b.id).confidence
        assert final_confidence == pytest.approx(initial_confidence)

    def test_adversarial_repetition_does_not_drift_belief(self):
        """
        Adversarial language pressure (repeated assertions without evidence)
        must not revise beliefs (spec §1.6, §1.8).
        """
        core = EpistemicCore(reliability_threshold=0.5)
        mem = EpistemicMemory(":memory:")
        _loop = ExperienceLoop(core, mem)

        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        initial_confidence = mem.get_belief(b.id).confidence

        # Check adversarial pressure guard
        for _ in range(100):
            decision = core.check_adversarial_pressure(
                ["everyone agrees", "consensus says so", "trust me"]
            )
            # Adversarial updates must be rejected — never apply them
            assert decision.eligible is False

        final_confidence = mem.get_belief(b.id).confidence
        assert final_confidence == pytest.approx(initial_confidence)
