"""
Tests for population synthesis.

Validates:
  - clustering is deterministic and preserves a minority of one
  - a holder's later stance stands, the earlier is kept and counted
  - the synthesis does not depend on input order, and ambiguous input
    (a repeated holder id, two stances at one latest `at`) is refused
  - every rendered position carries its citations
  - bridges are positions every speaking cluster shares
  - claims are OPINION proposals whose confidence is a share, not a verdict
  - interpretation is never generated and must be signed (ADR-0004)
  - the module has no import path to belief storage (ADR-0004 structural)
"""

import ast
import json
from pathlib import Path
from typing import ClassVar

import pytest

import episteme.population
from episteme import (
    Citation,
    Cluster,
    Holder,
    Interpretation,
    Synthesis,
    Utterance,
    agreement,
    claims,
    cluster_by_values,
    render,
    synthesise,
)
from episteme.models import BeliefType


def _cite(n: int) -> Citation:
    return Citation(source="events.jsonl", locator=f"seq={n}")


def _population():
    holders = [
        Holder("h1", {"autonomy": 0.9, "tradition": -0.8}),
        Holder("h2", {"autonomy": 0.8, "tradition": -0.7}),
        Holder("h3", {"autonomy": -0.9, "tradition": 0.9}),
        Holder("h4", {"autonomy": -0.8, "tradition": 0.8}),
        Holder("h5", {"autonomy": 0.0, "tradition": 0.0}),
    ]
    utterances = [
        Utterance("h1", "prop-1", "yes", "h1 votes yes", _cite(1), kind="vote", at=1),
        Utterance("h2", "prop-1", "yes", "h2 votes yes", _cite(2), kind="vote", at=2),
        Utterance("h3", "prop-1", "no", "h3 votes no", _cite(3), kind="vote", at=3),
        Utterance("h4", "prop-1", "yes", "h4 votes yes", _cite(4), kind="vote", at=4),
        Utterance("h5", "prop-1", "no", "h5 votes no", _cite(5), kind="vote", at=5),
        # h5 changes their mind later; the later stance stands.
        Utterance("h5", "prop-1", "yes", "h5 votes yes", _cite(6), kind="vote", at=6),
        # a topic only one holder speaks on
        Utterance("h3", "goal", "keep the old ways", "goal", _cite(7), kind="goal"),
    ]
    return holders, utterances


class TestClustering:
    def test_rejects_k_below_one(self):
        with pytest.raises(ValueError, match="k must be"):
            cluster_by_values([Holder("a")], 0)

    def test_empty_population_gives_no_clusters(self):
        assert cluster_by_values([], 3) == []

    def test_deterministic_and_order_independent(self):
        holders, _ = _population()
        first = cluster_by_values(holders, 2)
        second = cluster_by_values(list(reversed(holders)), 2)
        assert first == second
        assert first[0].seed == "h1"  # lexicographically first holder seeds

    def test_k_is_clamped_to_population(self):
        holders, _ = _population()
        clusters = cluster_by_values(holders, 10)
        assert len(clusters) == 5
        assert all(len(c.members) == 1 for c in clusters)

    def test_minority_of_one_survives(self):
        """Principle 8: a lone holder far from everyone is a cluster, not noise."""
        holders, _ = _population()
        clusters = cluster_by_values(holders, 3)
        sizes = sorted(len(c.members) for c in clusters)
        assert sizes == [1, 2, 2]
        lone = next(c for c in clusters if len(c.members) == 1)
        assert lone.members == ("h5",)

    def test_missing_axes_count_as_zero(self):
        holders = [Holder("a", {"x": 1.0}), Holder("b", {"y": 1.0}), Holder("c")]
        clusters = cluster_by_values(holders, 2)
        assert {m for c in clusters for m in c.members} == {"a", "b", "c"}


class TestAgreement:
    def test_identical_clusterings_agree_fully(self):
        holders, _ = _population()
        a = cluster_by_values(holders, 2)
        assert agreement(a, a) == 1.0

    def test_relabelling_does_not_matter(self):
        a = [Cluster("c0", "x", ("x", "y")), Cluster("c1", "z", ("z",))]
        b = [Cluster("k9", "z", ("z",)), Cluster("k8", "x", ("x", "y"))]
        assert agreement(a, b) == 1.0

    def test_partial_disagreement_is_fractional(self):
        a = [Cluster("c0", "x", ("x", "y")), Cluster("c1", "z", ("z",))]
        b = [Cluster("c0", "x", ("x",)), Cluster("c1", "y", ("y", "z"))]
        # pairs: xy together/apart, xz apart/apart, yz apart/together -> 1 of 3 agree
        assert agreement(a, b) == pytest.approx(1 / 3)

    def test_single_holder_agrees_trivially(self):
        a = [Cluster("c0", "x", ("x",))]
        assert agreement(a, a) == 1.0

    def test_different_holders_rejected(self):
        a = [Cluster("c0", "x", ("x",))]
        b = [Cluster("c0", "y", ("y",))]
        with pytest.raises(ValueError, match="different holders"):
            agreement(a, b)


class TestSynthesis:
    def test_unknown_holder_rejected(self):
        holders, _ = _population()
        stray = [Utterance("ghost", "t", "s", "text", _cite(0))]
        with pytest.raises(ValueError, match="not in the population"):
            synthesise(holders, stray)

    def test_latest_stance_stands_and_change_is_counted(self):
        holders, utterances = _population()
        s = synthesise(holders, utterances, k=2)
        yes = next(p for p in s.positions if p.statement == "prop-1: yes")
        no = next(p for p in s.positions if p.statement == "prop-1: no")
        assert "h5" in yes.holders and "h5" not in no.holders
        assert yes.changed_minds == 1 and no.changed_minds == 0
        # the earlier vote is still cited under the position h5 now holds
        assert _cite(5) in yes.citations and _cite(6) in yes.citations

    def test_support_is_reported_per_cluster(self):
        holders, utterances = _population()
        s = synthesise(holders, utterances, k=2)
        yes = next(p for p in s.positions if p.statement == "prop-1: yes")
        assert sum(yes.support_by_cluster.values()) == len(yes.holders)
        assert len(yes.support_by_cluster) == 2

    def test_bridge_is_shared_by_every_speaking_cluster(self):
        holders, utterances = _population()
        s = synthesise(holders, utterances, k=2)
        assert "prop-1: yes" in s.bridges
        assert "prop-1: no" not in s.bridges
        # a topic one cluster alone spoke on bridges nothing
        assert "goal: keep the old ways" not in s.bridges

    def test_positions_are_sorted_and_minority_kept(self):
        holders, utterances = _population()
        s = synthesise(holders, utterances, k=2)
        statements = [p.statement for p in s.positions]
        assert statements == sorted(statements)
        assert "goal: keep the old ways" in statements

    def test_reversed_utterance_list_gives_an_equal_synthesis(self):
        holders, utterances = _population()
        # two records of one stance at one `at`, cited differently: the tie
        # must not let list order choose the citation order
        utterances += [
            Utterance("h1", "prop-2", "yes", "h1 yes", _cite(8), at=7),
            Utterance("h1", "prop-2", "yes", "h1 yes again", _cite(9), at=7),
        ]
        forward = synthesise(holders, utterances, k=2)
        backward = synthesise(list(reversed(holders)), list(reversed(utterances)), k=2)
        assert forward == backward

    def test_repeated_holder_id_rejected(self):
        """Two copies of one id would count twice in every share."""
        holders, utterances = _population()
        with pytest.raises(ValueError, match=r"more than once: \['h2'\]"):
            synthesise([*holders, Holder("h2", {"autonomy": 0.1})], utterances)

    def test_different_stances_at_the_same_latest_at_rejected(self):
        """Neither stance is later, so which one stands would be list order."""
        holders, utterances = _population()
        utterances.append(
            Utterance("h5", "prop-1", "no", "h5 votes no", _cite(10), kind="vote", at=6)
        )
        with pytest.raises(ValueError, match="'h5' has different stances on 'prop-1'"):
            synthesise(holders, utterances)

    def test_no_utterances_is_an_empty_structure(self):
        holders, _ = _population()
        s = synthesise(holders, [], k=2)
        assert s.positions == [] and s.bridges == []
        assert s.holder_count == 5


class TestClaims:
    def test_claims_are_opinions_with_share_and_citations(self):
        holders, utterances = _population()
        s = synthesise(holders, utterances, k=2)
        out = claims(s, source="test")
        assert out and all(c.type == BeliefType.OPINION for c in out)
        yes = next(c for c in out if c.text == "prop-1: yes")
        assert yes.confidence == pytest.approx(4 / 5)
        assert yes.source == "test" and yes.domain == "population"
        assert "events.jsonl#seq=1" in json.loads(yes.context)

    def test_empty_population_share_is_zero(self):
        s = Synthesis(
            holder_count=0,
            clusters=[],
            positions=[
                episteme.population.Position("t: s", (), {}, (), 0),
            ],
            bridges=[],
        )
        assert claims(s)[0].confidence == 0.0


class TestRender:
    def test_every_position_line_carries_its_citations(self):
        holders, utterances = _population()
        text = render(synthesise(holders, utterances, k=2))
        position_lines = [line for line in text.splitlines() if " | " in line]
        assert position_lines
        for line in position_lines:
            assert "events.jsonl#seq=" in line
        assert "changed minds: 1" in text
        assert "bridges: " in text

    def test_no_bridges_renders_none(self):
        s = Synthesis(holder_count=1, clusters=[], positions=[], bridges=[])
        assert "bridges: none" in render(s)


class TestInterpretationNeverGenerated:
    """ADR-0004: the synthesis says what the structure is, a person says what it means."""

    def test_synthesis_carries_no_interpretation_by_default(self):
        holders, utterances = _population()
        s = synthesise(holders, utterances)
        assert s.interpretation is None
        assert "interpretation: none recorded" in render(s)

    def test_interpretation_must_be_signed(self):
        with pytest.raises(ValueError, match="author"):
            Interpretation(author="  ", text="it means something")
        with pytest.raises(ValueError, match="say something"):
            Interpretation(author="Dermot", text="")

    def test_signed_interpretation_renders_with_its_author(self):
        holders, utterances = _population()
        s = synthesise(holders, utterances)
        s.interpretation = Interpretation(author="Dermot", text="the split is on tradition")
        assert "interpretation (Dermot): the split is on tradition" in render(s)

    def test_module_defines_no_interpretation_producer(self):
        """No function in the module returns an Interpretation.

        The AST walk finds every function whose return annotation names
        ``Interpretation``; there must be none. A generated interpretation
        is the one output this module exists not to have.
        """
        tree = ast.parse(Path(episteme.population.__file__).read_text(encoding="utf-8"))
        producers = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.returns is not None
            and "Interpretation" in ast.dump(node.returns)
        ]
        assert producers == [], producers


class TestWriteIsolation:
    """ADR-0004 structural half: the synthesis has nothing to write beliefs through."""

    FORBIDDEN: ClassVar[set[str]] = {"episteme.core", "episteme.memory"}

    def test_population_does_not_import_belief_storage(self):
        tree = ast.parse(Path(episteme.population.__file__).read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        assert not (found & self.FORBIDDEN), sorted(found & self.FORBIDDEN)
