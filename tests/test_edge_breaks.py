"""
Deliberate breaks of ``episteme/edge.py`` that the suite let through, each
now failed by a test here.

On 27 November 2026 single-change breaks were made in the edge node, one at a
time, and the suite run against each. Every guard that ADR-0006 and ADR-0007
name failed on the break it guards. Some sentences of the two records could
still be broken with all 325 tests passing at 100% line coverage, because a
line that runs is not a line whose meaning is checked. Each test below quotes
the sentence it holds and names the break it fails on, so the measurement
can be repeated by hand.

These add to ``tests/test_edge.py`` and change nothing in it. The guards of
the two records are still the ones the records name; these are not ADR
guards. The breaks still open are listed in ``TestingStrategy.md`` under
*Known gaps*.
"""

from __future__ import annotations

import dataclasses
import json
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

import episteme.edge as en
from episteme import Belief, BeliefType, EpistemicMemory

ROOT = Path(__file__).resolve().parents[1]
REPORT = json.loads(
    (ROOT / "tests" / "fixtures" / "hybrid_agent_rules_first_report.json").read_text(
        encoding="utf-8"
    )
)
KIND = "compute.compare_windows"
OWN_P95 = REPORT["derived"][0]["data"]["p95_change_pct"]

# The tests' own settings, the same as tests/test_edge.py: the mechanism has none built in.
POLICY = en.Policy(
    ground_truth_weight=Fraction(1), consistency_weight=Fraction(1, 2),
    failure_multiple=Fraction(2), discount=Fraction(9, 10), ceiling=Fraction(9, 10),
    own_reliability=Fraction(4, 5), cap=Fraction(2), audit_rate=Fraction(1, 5),
    drift_window=5,
    facets={"ground truth": "accuracy", "consistency": "consistency",
            "self-contradiction": "honesty", "drift": "honesty", "timeliness": "timeliness"},
)
CHECK = en.P95Check(spread_pp=Fraction(75), drift_limit_pp=Fraction(10))

# 19/28: the neutral Beta(1, 1), discounted by 9/10, plus one ground-truth pass.
ONE_PASS = Fraction(19, 28)


@pytest.fixture
def hub_for():
    """Build receiving nodes, each with one belief at the uniform prior; close their stores."""
    stores: list[EpistemicMemory] = []

    def build(nodes, *, unverified=()):
        ledger = en.SourceLedger(POLICY)
        for node_id in nodes:
            ledger.enrol(node_id, reason="test")
            if node_id not in unverified:
                # The only way a test gives a source weight: no figure can be set.
                ledger.record_ground_truth(node_id, KIND, correct=True, against="setup")
        memory = EpistemicMemory()
        stores.append(memory)
        belief = Belief("checkout p95 regressed", BeliefType.THEORY, 0.5, "checkout")
        memory.add_belief(belief)
        hub = en.EdgeNode("hub", memory, ledger, [en.Route(KIND, belief.id, en.p95_rose)],
                          comparators={KIND: CHECK.degree},
                          deviations={KIND: (CHECK.deviation, CHECK.drift_limit_pp)},
                          audit_salt=b"test")
        return hub, belief.id

    yield build
    for memory in stores:
        memory.close()


def _report(name, p95_change=None):
    """The recorded report with its one derived result renamed, so it is new evidence."""
    report = json.loads(json.dumps(REPORT))
    report["derived"][0]["id"] = f"derived:{name}"
    report["derived"][0]["summary"] = f"comparison {name}"
    if p95_change is not None:
        report["derived"][0]["data"]["p95_change_pct"] = p95_change
    return report


def _packet(node_id, report=REPORT):
    return en.packet_from_report(node_id, None, report, sent_at="t")


def _checks(ledger, node_id):
    """The reasons of every check and suspension recorded for *node_id* after its setup."""
    return [e.reason for e in ledger.entries
            if e.node_id == node_id and e.action in ("check", "suspend")
            and e.reason != "ground truth: setup"]


# --- ADR-0006 ------------------------------------------------------------------


def test_a_proposed_action_never_reaches_the_packet_even_shaped_as_an_observation():
    """ADR-0006: "Its proposed actions are not evidence of anything."

    The recorded report proposes none (its ``actions`` is empty), so the packet
    test in ``test_edge.py`` cannot tell a packet that drops actions from one
    that would carry them. hybrid-agent's own shape for an action is not
    recorded in this repository; this one is the worst case, an action shaped
    exactly like a derived result of a routed kind.

    Break: add ``report["actions"]`` to the entries ``packet_from_report`` reads.
    """
    report = json.loads(json.dumps(REPORT))
    report["actions"] = [{"id": "action:roll-back", "source": KIND,
                          "summary": "roll back 4.12.0", "data": {"p95_change_pct": 500.0}}]
    packet = _packet("edge-a", report)
    assert packet == _packet("edge-a")
    assert b"roll" not in packet.body()


# --- ADR-0007 section 2: per context, and multi-faceted within it ----------------


def test_a_check_in_one_context_leaves_every_facet_of_another_as_it_was():
    """ADR-0007 s. 2: "a failure in one leaves the others as they were", and "a
    facet not yet checked neither raises nor lowers it"; s. 10's floor: "trust
    never transfers between contexts".

    ``test_edge.py`` shows this for one facet. With several, a facet checked
    only at night must not count as checked by day.

    Break: in ``SourceLedger.facets``, match the source alone (``if node == node_id``).
    """
    day, night = f"{KIND}@day", f"{KIND}@night"
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("edge-a", reason="test")
    ledger.record_ground_truth("edge-a", day, correct=True, against="meter")
    by_day = (ledger.facets("edge-a", day), ledger.trust("edge-a", day),
              ledger.weight("edge-a", day))
    assert by_day == ({"accuracy": ONE_PASS}, ONE_PASS, ONE_PASS)
    ledger.record_timeliness("edge-a", night, degree=Fraction(0), detail="late at night")
    ledger.record_behaviour("edge-a", night, finding="drift", detail="at night")
    assert set(ledger.facets("edge-a", night)) == {"honesty", "timeliness"}
    assert (ledger.facets("edge-a", day), ledger.trust("edge-a", day),
            ledger.weight("edge-a", day)) == by_day


# --- ADR-0007 section 4: consistency with other data sources --------------------


def test_two_references_from_one_group_count_once_in_a_consistency_check(hub_for):
    """ADR-0007 s. 4: "Each independent group counts once."

    ``test_edge.py`` shows a declared group counting once when its reports are
    aggregated. Here the group is the reference a new source is checked
    against: two verified peers that share firmware are one witness, not two.

    Break: drop ``or ref.group in groups_used`` in ``EdgeNode._check_consistency``.
    """
    hub, _ = hub_for(["ref-1", "ref-2", "new"], unverified={"new"})
    hub.ledger.declare_group("same-firmware", ["ref-1", "ref-2"], reason="test")
    for node_id in ("ref-1", "ref-2", "new"):
        assert hub.receive(_packet(node_id))
    hub.close_round()
    assert _checks(hub.ledger, "new") == ["consistency with ref-1"]
    assert hub.ledger.trust("new", KIND) == Fraction(14, 23)  # one pass: (0.9 + 1/2) / 2.3


def test_reports_on_different_beliefs_are_not_compared_with_each_other(hub_for):
    """ADR-0007 s. 8: a report on a belief is compared "with what the same node
    said before on that belief". For references the record does not name the
    belief; the module's own account does: "a source's items are compared
    with references on the same belief and kind". A source that finds
    checkout slower and search faster has not contradicted itself, and the
    node's own reading of checkout says nothing about its report on search.

    Breaks: key the source's history without the belief
    (``(s.node_id, s.context, "")`` in ``_check_against_own_history``); drop
    ``ref.belief_id != s.belief_id`` in ``_check_consistency``.
    """
    hub, checkout = hub_for(["edge-a"])
    search = Belief("search p95 regressed", BeliefType.THEORY, 0.5, "search")
    hub.memory.add_belief(search)

    def about(name):
        return lambda item: en.p95_rose(item) if name in item.item_id else None

    hub.routes = [en.Route(KIND, checkout, about("checkout")),
                  en.Route(KIND, search.id, about("search"))]
    hub.receive(_packet("edge-a", _report("checkout-1")))
    hub.close_round()
    hub.observe_own(_report("checkout-own"))
    hub.receive(_packet("edge-a", _report("search-1", p95_change=-30.0)))
    outcomes = {o.item_id: o for o in hub.close_round()}
    assert outcomes["derived:search-1"].revised and not outcomes["derived:search-1"].supporting
    assert hub.disputes == []
    assert _checks(hub.ledger, "edge-a") == []
    assert hub.ledger.is_verified("edge-a", KIND)


# --- ADR-0007 section 8: the covert node -----------------------------------------


def test_a_lean_below_the_references_is_drift_as_much_as_a_lean_above(hub_for):
    """ADR-0007 s. 8: "The receiving node averages a node's signed deviations
    from independent data over a stated window of reports; a mean beyond a
    stated limit is drift".

    ``test_edge.py`` shows a lean of twelve points above the references. A
    source that leans twelve below them, under-reporting a regression, is
    drifting as much.

    Break: test the mean without its sign removed (``if mean > limit``) in
    ``EdgeNode._track_drift``.
    """
    hub, belief_id = hub_for(["biased"])
    for n in range(POLICY.drift_window):
        hub.observe_own(REPORT)
        hub.receive(_packet("biased", _report(f"biased-{n}", round(OWN_P95 - 12, 1))))
        hub.close_round()
    reasons = _checks(hub.ledger, "biased")
    assert reasons[:-2] == ["consistency with self"] * POLICY.drift_window
    assert hub.disputes == []  # each report alone agreed well enough
    assert reasons[-2].startswith("drift: mean deviation") and reasons[-1] == reasons[-2]
    assert not hub.ledger.is_verified("biased", KIND)
    assert hub.review == [belief_id]


# --- ADR-0007 section 10: any figures a node may set ----------------------------

_FIGURES = ("ground_truth_weight", "consistency_weight", "failure_multiple", "discount", "ceiling")


def _fractions(low, high):
    return st.fractions(min_value=low, max_value=high, max_denominator=20)


@st.composite
def _figures(draw):
    """Figures a node may set, and one more figure from anywhere between -2 and 3."""
    ground_truth = draw(_fractions(Fraction(1, 20), 3))
    figures = {
        "ground_truth_weight": ground_truth,
        "consistency_weight": draw(_fractions(Fraction(1, 20), ground_truth)),
        "failure_multiple": draw(_fractions(1, 5)),
        "discount": draw(_fractions(Fraction(1, 20), 1)),
        "ceiling": draw(_fractions(Fraction(1, 20), Fraction(19, 20))),
    }
    return figures, draw(_fractions(-2, 3))


#: The tests' own figures, for the fixed examples.
_OWN = {name: getattr(POLICY, name) for name in _FIGURES}


def _mean_after(policy, check, *outcomes):
    """A facet's mean, before the ceiling, after *outcomes* of one kind of check from neutral."""
    ledger = en.SourceLedger(policy)
    ledger.enrol("edge-a", reason="test")
    for passed in outcomes:
        if check == "ground truth":
            ledger.record_ground_truth("edge-a", KIND, correct=passed, against="meter")
        else:
            ledger.record_consistency("edge-a", KIND, degree=Fraction(int(passed)),
                                      reference=en.SELF)
    last = [e for e in ledger.entries if e.action == "check"][-1]
    return last.alpha / (last.alpha + last.beta), ledger.trust("edge-a", KIND)


def _means_what_it_says(policy):
    """What sections 4, 8 and 10 say of any record, asserted of one built on *policy*."""
    neutral = Fraction(1, 2)
    rise = {}
    for check in ("ground truth", "consistency"):
        passed, trust = _mean_after(policy, check, True)
        failed, _ = _mean_after(policy, check, False)
        assert failed < neutral < passed  # a pass raises trust and a failure lowers it
        assert neutral - failed >= passed - neutral  # a failure weighs at least a success
        assert 0 < trust <= policy.ceiling < 1
        switched, _ = _mean_after(policy, check, True, False)
        recovered, _ = _mean_after(policy, check, False, True)
        assert switched <= recovered  # recent outcomes count most
        rise[check] = passed - neutral
    assert rise["ground truth"] >= rise["consistency"]  # ground truth weighs at least as much


@given(drawn=_figures())
@example(drawn=(_OWN, Fraction(11, 10)))
@example(drawn=(_OWN, Fraction(0)))
@example(drawn=(_OWN, Fraction(-1, 2)))
@example(drawn=(_OWN | {"ceiling": Fraction(2, 5)}, Fraction(1)))
@settings(deadline=None)
def test_any_figures_a_policy_accepts_keep_the_record_meaning_what_it_says(drawn):
    """ADR-0007 s. 10: "Context sets the figures; it cannot remove the floors."

    ``test_edge.py`` refuses seven settings by example. Here the question is
    put the other way round: either ``Policy`` refuses the figures, or the
    record built on them still means what sections 4, 8 and 10 say. A pass
    raises trust and a failure lowers it; a failure weighs at least as much
    as a success; ground truth weighs at least as much as consistency; of two
    records holding one pass and one failure, the one that failed more
    recently is never the higher ("Recent outcomes count most"); and trust
    stays above 0 and under a ceiling below 1.

    Each case is a set of figures a node may set, tried as it stands and then
    with each figure in turn replaced by one drawn from anywhere between -2
    and 3. The fixed examples put 11/10, 0 and -1/2 in each place of the
    tests' own figures, and set a ceiling under the neutral 1/2, so each
    break below fails on every run. The search around them is hypothesis's
    and differs from run to run: what else it would catch is not claimed.

    Breaks, the first three in ``Policy.__post_init__``: accept a discount
    above 1 (``if not 0 < self.discount``); leave ``consistency_weight`` out
    of the figures that must be positive; accept a ceiling of 0 or less
    (``if not self.ceiling < 1``). And in ``SourceLedger.facet``: hold a
    ceiling no lower than neutral (``max(self.policy.ceiling, Fraction(1, 2))``).
    """
    figures, astray = drawn
    for name in (None, *_FIGURES):
        candidate = figures if name is None else figures | {name: astray}
        try:
            policy = dataclasses.replace(POLICY, **candidate)
        except ValueError:
            continue
        _means_what_it_says(policy)
