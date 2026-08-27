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

    def test_same_evidence_cannot_support_and_dispute(self, setup):
        """The same deduplicated evidence must not land on both sides of a
        belief - that would leave it DISPUTED against itself."""
        _core, mem, loop = setup
        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        obs_kwargs = {
            "content": "One measurement, read twice.",
            "source": "instrument",
            "reliability": 0.9,
            "belief_ids": [b.id],
        }

        r1 = loop.observe_outcome(**obs_kwargs, supporting=True)
        assert r1[0].revised is True

        r2 = loop.observe_outcome(**obs_kwargs, supporting=False)
        assert r2[0].revised is False

        updated = mem.get_belief(b.id)
        assert set(updated.evidence_ids) & set(updated.counter_evidence_ids) == set()
        assert updated.state != BeliefState.DISPUTED

    def test_conflicting_reliability_for_same_context_fails_loudly(self, setup):
        """A re-observation of the same content/source with a different
        reliability is an unresolvable conflict with the stored (immutable)
        evidence, not something to silently ignore."""
        _core, mem, loop = setup
        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        loop.observe_outcome(
            content="Same reading.", source="sensor", reliability=0.9, belief_ids=[b.id]
        )
        with pytest.raises(ValueError, match="reliability"):
            loop.observe_outcome(
                content="Same reading.", source="sensor", reliability=0.1, belief_ids=[b.id]
            )

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
        """Confidence must not change unless evidence targets the belief.

        The turns drive the real loop path (observations are recorded), but
        none of them names the belief - so its confidence must be
        byte-identical afterwards, not merely approximately equal.
        """
        core = EpistemicCore(reliability_threshold=0.5)
        mem = EpistemicMemory(":memory:")
        loop = ExperienceLoop(core, mem)

        b = make_belief(confidence=0.7)
        mem.add_belief(b)

        initial_confidence = mem.get_belief(b.id).confidence

        for turn in range(200):
            results = loop.observe_outcome(
                content=f"Ambient observation {turn}.",
                source="sensor",
                reliability=0.9,
                belief_ids=[],
            )
            assert results == []

        final_confidence = mem.get_belief(b.id).confidence
        assert final_confidence == initial_confidence

    def test_adversarial_repetition_does_not_drift_belief(self):
        """
        Adversarial repetition of one observation must not compound
        (spec §1.6, §1.8): the first application may revise, every repeat is
        refused by the context_hash deduplication, and confidence after M
        submissions equals confidence after 1.
        """
        core = EpistemicCore(reliability_threshold=0.5)
        mem = EpistemicMemory(":memory:")
        loop = ExperienceLoop(core, mem)

        b = make_belief(confidence=0.5)
        mem.add_belief(b)

        obs_kwargs = {
            "content": "The claim is definitely, definitely true.",
            "source": "insistent-source",
            "reliability": 0.9,
            "belief_ids": [b.id],
        }

        first = loop.observe_outcome(**obs_kwargs)
        assert first[0].revised is True
        confidence_after_one = mem.get_belief(b.id).confidence

        for _ in range(99):
            repeat = loop.observe_outcome(**obs_kwargs)
            assert repeat[0].revised is False

        updated = mem.get_belief(b.id)
        assert updated.confidence == confidence_after_one
        assert updated.evidence_ids == [first[0].evidence_id]
