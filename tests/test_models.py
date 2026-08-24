"""
Tests for EPISTEME data models (Belief, Evidence, BeliefRevision).
"""

from datetime import UTC, datetime

import pytest

from episteme.models import Belief, BeliefRevision, BeliefState, BeliefType, Evidence

# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_valid_evidence_creation(self):
        e = Evidence(summary="Test", reliability=0.8, context_hash="abc123")
        assert e.summary == "Test"
        assert e.reliability == 0.8
        assert e.context_hash == "abc123"
        assert e.id is not None

    def test_evidence_id_auto_generated(self):
        e1 = Evidence(summary="A", reliability=0.5, context_hash="h1")
        e2 = Evidence(summary="B", reliability=0.5, context_hash="h2")
        assert e1.id != e2.id

    def test_evidence_reliability_out_of_range_low(self):
        with pytest.raises(ValueError, match="reliability"):
            Evidence(summary="x", reliability=-0.1, context_hash="h")

    def test_evidence_reliability_out_of_range_high(self):
        with pytest.raises(ValueError, match="reliability"):
            Evidence(summary="x", reliability=1.1, context_hash="h")

    def test_evidence_boundary_values(self):
        e0 = Evidence(summary="x", reliability=0.0, context_hash="h")
        e1 = Evidence(summary="x", reliability=1.0, context_hash="h2")
        assert e0.reliability == 0.0
        assert e1.reliability == 1.0

    def test_evidence_timestamp_utc(self):
        e = Evidence(summary="x", reliability=0.5, context_hash="h")
        assert e.timestamp.tzinfo is not None


# ---------------------------------------------------------------------------
# Belief
# ---------------------------------------------------------------------------


class TestBelief:
    def test_valid_belief_creation(self):
        b = Belief(
            statement="The sky is blue.",
            type=BeliefType.FACT,
            confidence=0.95,
            domain="science",
        )
        assert b.statement == "The sky is blue."
        assert b.type == BeliefType.FACT
        assert b.confidence == 0.95
        assert b.domain == "science"
        assert b.id is not None
        assert b.state == BeliefState.ACTIVE

    def test_belief_confidence_out_of_range_low(self):
        with pytest.raises(ValueError, match="confidence"):
            Belief(
                statement="x",
                type=BeliefType.FACT,
                confidence=-0.1,
                domain="d",
            )

    def test_belief_confidence_out_of_range_high(self):
        with pytest.raises(ValueError, match="confidence"):
            Belief(
                statement="x",
                type=BeliefType.FACT,
                confidence=1.1,
                domain="d",
            )

    def test_belief_type_string_coercion(self):
        b = Belief(statement="x", type="THEORY", confidence=0.5, domain="d")
        assert b.type == BeliefType.THEORY

    def test_belief_state_string_coercion(self):
        b = Belief(
            statement="x",
            type=BeliefType.FACT,
            confidence=0.5,
            domain="d",
            state="DISPUTED",
        )
        assert b.state == BeliefState.DISPUTED

    def test_belief_id_auto_generated(self):
        b1 = Belief(statement="A", type=BeliefType.FACT, confidence=0.5, domain="d")
        b2 = Belief(statement="B", type=BeliefType.FACT, confidence=0.5, domain="d")
        assert b1.id != b2.id

    def test_belief_evidence_ids_default_empty(self):
        b = Belief(statement="x", type=BeliefType.FACT, confidence=0.5, domain="d")
        assert b.evidence_ids == []
        assert b.counter_evidence_ids == []

    def test_belief_type_values(self):
        for t in (BeliefType.FACT, BeliefType.THEORY, BeliefType.OPINION, BeliefType.FICTION):
            b = Belief(statement="x", type=t, confidence=0.5, domain="d")
            assert b.type == t


# ---------------------------------------------------------------------------
# BeliefRevision
# ---------------------------------------------------------------------------


class TestBeliefRevision:
    def _make_state(self, conf: float) -> dict:
        return {
            "id": "b1",
            "statement": "test",
            "type": "FACT",
            "confidence": conf,
            "domain": "d",
            "evidence_ids": [],
            "counter_evidence_ids": [],
            "state": "ACTIVE",
            "created_at": datetime.now(UTC).isoformat(),
        }

    def test_revision_id_auto_generated(self):
        r = BeliefRevision(
            belief_id="b1",
            previous_state=self._make_state(0.5),
            new_state=self._make_state(0.7),
            evidence_id="e1",
            reason="test",
        )
        assert r.id is not None

    def test_revision_timestamp_utc(self):
        r = BeliefRevision(
            belief_id="b1",
            previous_state=self._make_state(0.5),
            new_state=self._make_state(0.7),
            evidence_id="e1",
            reason="test",
        )
        assert r.revised_at.tzinfo is not None
