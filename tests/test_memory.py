"""
Tests for EpistemicMemory (SQLite-backed append-only store).

Validates:
  - Belief add / get / list
  - Evidence add / get
  - Belief revision (append-only, history queryable)
  - Duplicate-add protection
  - Missing belief handling
"""

import pytest

from episteme.memory import EpistemicMemory
from episteme.models import Belief, BeliefState, BeliefType, Evidence


def make_belief(**kwargs) -> Belief:
    defaults = {
        "statement": "Water is H2O.",
        "type": BeliefType.FACT,
        "confidence": 0.99,
        "domain": "chemistry",
    }
    defaults.update(kwargs)
    return Belief(**defaults)


def make_evidence(**kwargs) -> Evidence:
    defaults = {
        "summary": "Lab measurement confirmed.",
        "reliability": 0.95,
        "context_hash": "ctx_chem_001",
    }
    defaults.update(kwargs)
    return Evidence(**defaults)


@pytest.fixture
def mem():
    with EpistemicMemory(":memory:") as m:
        yield m


class TestEvidenceStorage:
    def test_add_and_get_evidence(self, mem):
        e = make_evidence()
        mem.add_evidence(e)
        fetched = mem.get_evidence(e.id)
        assert fetched is not None
        assert fetched.id == e.id
        assert fetched.summary == e.summary
        assert fetched.reliability == pytest.approx(e.reliability)

    def test_get_missing_evidence_returns_none(self, mem):
        assert mem.get_evidence("nonexistent") is None

    def test_add_evidence_idempotent(self, mem):
        e = make_evidence()
        mem.add_evidence(e)
        mem.add_evidence(e)  # should not raise
        assert mem.get_evidence(e.id) is not None


class TestBeliefStorage:
    def test_add_and_get_belief(self, mem):
        b = make_belief()
        mem.add_belief(b)
        fetched = mem.get_belief(b.id)
        assert fetched is not None
        assert fetched.id == b.id
        assert fetched.statement == b.statement
        assert fetched.confidence == pytest.approx(b.confidence)
        assert fetched.type == b.type

    def test_get_missing_belief_returns_none(self, mem):
        assert mem.get_belief("nonexistent") is None

    def test_add_duplicate_belief_raises(self, mem):
        b = make_belief()
        mem.add_belief(b)
        with pytest.raises(ValueError, match="already exists"):
            mem.add_belief(b)

    def test_list_beliefs_empty(self, mem):
        assert mem.list_beliefs() == []

    def test_list_beliefs_all(self, mem):
        b1 = make_belief(statement="A", domain="d1")
        b2 = make_belief(statement="B", domain="d2")
        mem.add_belief(b1)
        mem.add_belief(b2)
        beliefs = mem.list_beliefs()
        assert len(beliefs) == 2

    def test_list_beliefs_filtered_by_domain(self, mem):
        b1 = make_belief(statement="A", domain="physics")
        b2 = make_belief(statement="B", domain="chemistry")
        mem.add_belief(b1)
        mem.add_belief(b2)
        physics = mem.list_beliefs(domain="physics")
        assert len(physics) == 1
        assert physics[0].domain == "physics"

    def test_list_beliefs_filtered_by_state(self, mem):
        b1 = make_belief(statement="A", state=BeliefState.ACTIVE)
        b2 = make_belief(statement="B", state=BeliefState.DISPUTED)
        mem.add_belief(b1)
        mem.add_belief(b2)
        active = mem.list_beliefs(state=BeliefState.ACTIVE)
        assert len(active) == 1
        assert active[0].state == BeliefState.ACTIVE


class TestBeliefRevision:
    def test_revise_confidence(self, mem):
        b = make_belief(confidence=0.5)
        e = make_evidence()
        mem.add_belief(b)
        mem.add_evidence(e)

        mem.revise_belief(
            b.id,
            e,
            new_confidence=0.75,
            reason="Strong evidence received.",
        )

        updated = mem.get_belief(b.id)
        assert updated.confidence == pytest.approx(0.75)

    def test_revision_history_appended(self, mem):
        b = make_belief(confidence=0.5)
        e1 = make_evidence(context_hash="ctx1")
        e2 = make_evidence(context_hash="ctx2", summary="Second obs")
        mem.add_belief(b)
        mem.add_evidence(e1)
        mem.add_evidence(e2)

        mem.revise_belief(b.id, e1, new_confidence=0.6, reason="First revision")
        mem.revise_belief(b.id, e2, new_confidence=0.7, reason="Second revision")

        revisions = mem.get_revisions(b.id)
        assert len(revisions) == 2
        assert revisions[0].reason == "First revision"
        assert revisions[1].reason == "Second revision"

    def test_revision_previous_state_preserved(self, mem):
        b = make_belief(confidence=0.5)
        e = make_evidence()
        mem.add_belief(b)
        mem.add_evidence(e)

        revision = mem.revise_belief(
            b.id, e, new_confidence=0.8, reason="evidence"
        )

        assert revision.previous_state["confidence"] == pytest.approx(0.5)
        assert revision.new_state["confidence"] == pytest.approx(0.8)

    def test_revise_missing_belief_raises(self, mem):
        e = make_evidence()
        mem.add_evidence(e)
        with pytest.raises(ValueError, match="not found"):
            mem.revise_belief("nonexistent", e, new_confidence=0.5, reason="x")

    def test_revise_state(self, mem):
        b = make_belief()
        e = make_evidence()
        mem.add_belief(b)
        mem.add_evidence(e)

        mem.revise_belief(b.id, e, new_state=BeliefState.DISPUTED, reason="counter")
        updated = mem.get_belief(b.id)
        assert updated.state == BeliefState.DISPUTED

    def test_revise_evidence_ids(self, mem):
        b = make_belief()
        e = make_evidence()
        mem.add_belief(b)
        mem.add_evidence(e)

        mem.revise_belief(b.id, e, new_evidence_ids=[e.id], reason="added evidence")
        updated = mem.get_belief(b.id)
        assert e.id in updated.evidence_ids

    def test_beliefs_never_deleted(self, mem):
        """After multiple revisions the belief is still retrievable."""
        b = make_belief(confidence=0.1)
        mem.add_belief(b)
        for i in range(5):
            e = make_evidence(context_hash=f"ctx{i}", summary=f"obs{i}")
            mem.add_evidence(e)
            mem.revise_belief(b.id, e, new_confidence=0.1 + 0.1 * i, reason="inc")

        assert mem.get_belief(b.id) is not None
        assert len(mem.get_revisions(b.id)) == 5
