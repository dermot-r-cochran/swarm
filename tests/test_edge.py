"""
Tests for episteme/edge.py, the edge node of ADR-0006 and ADR-0007
(accepted 23 November 2026; each names its guard tests here).

Trust rests only on what the author ruled it may (23 November 2026):
behaviour over time and consistency with other data sources, recorded by the
receiving node itself. Never on a signature, a peer's vouching or a figure a
person sets. These tests pin that, together with the guards the two records
name: a hypothesis is never stored as a belief, correlated sources count
once, a new source moves no belief, a source cannot raise its own weight, one
group's influence on a belief is capped, aggregation is exact and
order-independent, and neither revocation nor suspension recomputes a belief.
"""

import ast
import dataclasses
import hashlib
import inspect
import json
import random
from fractions import Fraction
from pathlib import Path

import pytest

import episteme.edge as en
from episteme import Belief, BeliefType, EpistemicMemory

ROOT = Path(__file__).resolve().parents[1]
REPORT = json.loads(
    (ROOT / "tests" / "fixtures" / "hybrid_agent_rules_first_report.json").read_text(
        encoding="utf-8"
    )
)
KIND = "compute.compare_windows"
DERIVED = "derived:checkout:before_after_deploy"


# The tests' own settings: the mechanism has none built in.
POLICY = en.Policy(
    ground_truth_weight=Fraction(1), consistency_weight=Fraction(1, 2),
    failure_multiple=Fraction(2), discount=Fraction(9, 10), ceiling=Fraction(9, 10),
    own_reliability=Fraction(4, 5), cap=Fraction(2), audit_rate=Fraction(1, 5),
    drift_window=5,
)
CHECK = en.P95Check(spread_pp=Fraction(75), drift_limit_pp=Fraction(10))


_OPEN: list[EpistemicMemory] = []


@pytest.fixture(autouse=True)
def _close_stores():
    yield
    while _OPEN:
        _OPEN.pop().close()


def _hub(nodes, *, verified=True, group=None, signed=True, policy=None):
    """A receiving node with one belief at the uniform prior and *nodes* enrolled.

    With *verified*, each node has passed one ground-truth check, the only
    way a test gives a source weight: no figure can be set.
    """
    ledger = en.SourceLedger(policy or POLICY)
    for node_id in nodes:
        verifier = en.HmacSha256(node_id.encode()) if signed else None
        ledger.enrol(node_id, verifier, reason="test")
        if verified:
            ledger.record_ground_truth(node_id, KIND, correct=True, against="setup")
    if group:
        ledger.declare_group(group, nodes, reason="test")
    memory = EpistemicMemory()
    _OPEN.append(memory)
    belief = Belief("p95 regressed", BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(belief)
    hub = en.EdgeNode("hub", memory, ledger, [en.Route(KIND, belief.id, en.p95_rose)],
                      comparators={KIND: CHECK.degree},
                      deviations={KIND: (CHECK.deviation, CHECK.drift_limit_pp)},
                      audit_salt=b"test")
    return hub, belief.id


def _packet(node_id, report=REPORT, *, signed=True, **kw):
    signer = en.HmacSha256(node_id.encode()) if signed else None
    return en.packet_from_report(node_id, signer, report, sent_at="t", **kw)


def _distinct_report(n, p95_change=None):
    """A report whose one derived result has a distinct id, so it is new evidence."""
    report = json.loads(json.dumps(REPORT))
    report["derived"][0]["id"] = f"derived:{n}"
    report["derived"][0]["summary"] = f"comparison {n}"
    if p95_change is not None:
        report["derived"][0]["data"]["p95_change_pct"] = p95_change
    return report


# 19/28: the neutral Beta(1, 1), discounted by 9/10, plus one ground-truth pass.
ONE_PASS = Fraction(19, 28)


# --- what a packet carries -------------------------------------------------


def test_packet_carries_evidence_proposals_and_unknowns_but_no_actions_or_beliefs():
    packet = _packet("edge-a")
    assert [i.item_id for i in packet.items] == [
        e["id"] for e in REPORT["observations"] + REPORT["derived"]
    ]
    assert packet.hypotheses == tuple(h["statement"] for h in REPORT["hypotheses"])
    assert packet.unknowns == tuple(REPORT["unknowns"])
    wire = json.loads(packet.body())
    assert set(wire) == {"scheme", "node_id", "sent_at", "items", "hypotheses", "unknowns"}
    assert wire["scheme"] == "hmac-sha256"
    samples = next(i for i in packet.items if i.item_id == "metrics:checkout").data["samples"]
    assert samples.startswith("sha256:")  # lists travel as digests


def test_a_report_not_awaiting_review_is_refused():
    report = dict(REPORT, status="done")
    with pytest.raises(ValueError, match="awaiting_human_review"):
        _packet("edge-a", report)


# --- admission ---------------------------------------------------------------


def test_unenrolled_forged_and_revoked_packets_are_refused_whole():
    hub, _ = _hub(["edge-a", "edge-b"])
    assert not hub.receive(_packet("edge-x"))
    assert not hub.receive(_packet(en.SELF))  # no source may claim the node's own id
    forged = en.sign(_packet("edge-a"), en.HmacSha256(b"not-the-key"))
    assert not hub.receive(forged)
    hub.ledger.revoke("edge-b", reason="device lost")
    assert not hub.receive(_packet("edge-b"))
    assert [why for _, why in hub.refused] == [
        "not enrolled",
        "not enrolled",
        "integrity: signature does not verify",
        "revoked",
    ]
    assert hub.close_round() == []


def test_a_hypothesis_is_held_as_a_claim_and_never_stored_as_a_belief():
    hub, belief_id = _hub(["edge-a"])
    hub.receive(_packet("edge-a"))
    hub.close_round()
    assert [b.id for b in hub.memory.list_beliefs()] == [belief_id]
    assert [c.text for c in hub.claims] == [h["statement"] for h in REPORT["hypotheses"]]
    assert all(c.source == "node:edge-a" for c in hub.claims)


def test_a_new_source_is_neutral_and_unverified_and_sends_only_leads():
    hub, belief_id = _hub(["edge-a"], verified=False)
    assert hub.ledger.trust("edge-a", KIND) == Fraction(1, 2)
    assert not hub.ledger.is_verified("edge-a", KIND)
    hub.receive(_packet("edge-a"))
    (outcome,) = hub.close_round()
    assert (outcome.offered, outcome.revised) == (0, False)
    assert outcome.reason.startswith("lead")
    assert hub.memory.get_revisions(belief_id) == []


def test_a_source_can_lower_its_own_weight_but_never_raise_it():
    hub, _ = _hub(["low", "high"])
    hub.receive(_packet("low", stated={KIND: Fraction(1, 2)}))
    hub.receive(_packet("high", stated={KIND: Fraction(1)}))
    offered = {o.node_id: o.offered for o in hub.close_round()}
    assert offered == {"low": Fraction(1, 2), "high": ONE_PASS}


def test_no_figure_a_source_sends_changes_the_trust_held_in_it():
    # A packet carries reports, never a figure from the sender's own policy or record.
    assert {f.name for f in dataclasses.fields(en.Packet)} == {
        "node_id", "sent_at", "items", "hypotheses", "unknowns", "scheme", "signature"
    }
    hub, _ = _hub(["edge-a"])
    before = (hub.ledger.trust("edge-a", KIND), len(hub.ledger.entries))
    hub.receive(_packet("edge-a", stated={KIND: Fraction(1)}))
    assert (hub.ledger.trust("edge-a", KIND), len(hub.ledger.entries)) == before


# --- the cryptographic layer ---------------------------------------------------


class _ToyScheme:
    """A second scheme for tests only: NOT a signature, just proof of the seam."""

    scheme = "toy-sha256"
    symmetric = False

    def __init__(self, tag: bytes) -> None:
        self._tag = tag

    def fingerprint(self) -> str:
        return "toy:" + self._tag.hex()

    def sign(self, body: bytes) -> str:
        return hashlib.sha256(self._tag + body).hexdigest()

    def verify(self, body: bytes, signature: str) -> bool:
        return self.sign(body) == signature


def test_trust_and_aggregation_work_unchanged_with_another_scheme():
    hub, belief_id = _hub([])
    hub.ledger.enrol("edge-t", _ToyScheme(b"t"), reason="test")
    hub.ledger.record_ground_truth("edge-t", KIND, correct=True, against="setup")
    packet = en.packet_from_report("edge-t", _ToyScheme(b"t"), REPORT, sent_at="t")
    assert packet.scheme == "toy-sha256"
    assert hub.receive(packet)
    (outcome,) = hub.close_round()
    assert outcome.revised and outcome.applied == ONE_PASS
    assert hub.memory.get_belief(belief_id).confidence > 0.5
    assert hub.ledger.entries[0].detail == "toy-sha256 (asymmetric) toy:74"


def test_a_packet_in_a_scheme_other_than_the_enrolled_one_is_refused():
    hub, _ = _hub(["edge-a"])
    assert not hub.receive(en.sign(_packet("edge-a"), _ToyScheme(b"edge-a")))
    assert hub.refused == [
        ("edge-a", "integrity: scheme 'toy-sha256' is not the enrolled 'hmac-sha256'")
    ]


def test_the_scheme_is_covered_by_the_signature():
    hub, _ = _hub(["edge-a"])
    packet = _packet("edge-a")
    tampered = en.Packet(packet.node_id, packet.sent_at, packet.items, packet.hypotheses,
                         packet.unknowns, scheme="other", signature=packet.signature)
    assert tampered.body() != packet.body()
    assert not hub.receive(tampered)


def test_enrolment_records_the_scheme_and_a_fingerprint_never_the_secret():
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("edge-a", en.HmacSha256(b"s3cret"), reason="test")
    (entry,) = ledger.entries
    assert entry.detail.startswith("hmac-sha256 (symmetric) sha256:")
    assert b"s3cret".hex() not in entry.detail and "s3cret" not in repr(en.HmacSha256(b"s3cret"))
    with pytest.raises(ValueError, match="must not be empty"):
        en.HmacSha256(b"")


# --- trust does not rest on signatures ----------------------------------------


def test_a_signature_never_changes_an_items_weight():
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("signed", en.HmacSha256(b"k"), reason="test")
    ledger.enrol("unsigned", reason="test")
    for node in ("signed", "unsigned"):
        ledger.record_ground_truth(node, KIND, correct=True, against="setup")
    memory = EpistemicMemory()
    _OPEN.append(memory)
    belief = Belief("p95 regressed", BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(belief)
    hub = en.EdgeNode("hub", memory, ledger, [en.Route(KIND, belief.id, en.p95_rose)])
    assert hub.receive(en.packet_from_report("signed", en.HmacSha256(b"k"), REPORT, sent_at="t"))
    assert hub.receive(en.packet_from_report("unsigned", None, REPORT, sent_at="t"))
    assert hub.received == [("signed", "verified"), ("unsigned", "unchecked")]
    offered = {o.node_id: (o.offered, o.applied) for o in hub.close_round()}
    assert offered["signed"] == offered["unsigned"] == (ONE_PASS, ONE_PASS)


def test_a_node_enrolled_with_a_verifier_must_pass_its_integrity_check():
    hub, _ = _hub(["edge-a"])
    unsigned = _packet("edge-a", signed=False)
    assert unsigned.signature == "" and unsigned.scheme == ""
    assert not hub.receive(unsigned)
    assert hub.refused == [("edge-a", "integrity: scheme '' is not the enrolled 'hmac-sha256'")]


def test_enrolment_gives_no_weight():
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("edge-a", reason="test")
    assert ledger.is_enrolled("edge-a") and ledger.verifier("edge-a") is None
    assert ledger.entries[0].detail == "no integrity check"
    assert ledger.weight("edge-a", KIND) == 0
    with pytest.raises(ValueError, match="own id"):
        ledger.enrol(en.SELF, reason="test")


def test_an_impostor_using_an_enrolled_id_is_bounded_by_the_cap_and_by_ground_truth():
    hub, belief_id = _hub(["edge-a"], signed=False)  # no integrity check: ids can be claimed
    for n in range(20):
        assert hub.receive(_packet("edge-a", _distinct_report(f"x{n}"), signed=False))
        hub.close_round()
    assert hub.memory.get_belief(belief_id).confidence <= 0.75 + 1e-12
    review = hub.check_ground_truth("edge-a", "derived:x0", correct=False, against="inspection")
    assert review == [belief_id]
    assert hub.ledger.weight("edge-a", KIND) == 0


# --- trust rests on behaviour over time and consistency ---------------------------


def test_no_method_takes_a_figure_a_vouch_or_a_count():
    public = {n for n, _ in inspect.getmembers(en.SourceLedger) if not n.startswith("_")}
    writers = {"enrol", "declare_group", "revoke", "record_ground_truth", "record_consistency",
               "record_behaviour"}
    readers = {"entries", "is_enrolled", "is_revoked", "verifier", "is_verified", "trust",
               "weight", "group"}
    assert public == writers | readers
    for name in writers:
        params = set(inspect.signature(getattr(en.SourceLedger, name)).parameters)
        assert not params & {"trust", "figure", "score", "vouch", "count", "weight"}


def test_agreement_among_unverified_peers_verifies_nothing():
    nodes = [f"edge-{i}" for i in range(10)]  # ten independent groups, all agreeing
    hub, belief_id = _hub(nodes, verified=False)
    entries = hub.ledger.entries
    for round_ in range(3):
        for n in nodes:
            hub.receive(_packet(n, _distinct_report(f"{n}-{round_}")))
        hub.close_round()
    assert hub.ledger.entries == entries
    assert not any(hub.ledger.is_verified(n, KIND) for n in nodes)
    assert hub.memory.get_revisions(belief_id) == []


def test_consistency_with_the_nodes_own_data_verifies_a_source():
    hub, _ = _hub(["edge-a"], verified=False)
    hub.observe_own(REPORT)
    hub.receive(_packet("edge-a"))
    outcomes = {o.node_id: o for o in hub.close_round()}
    assert outcomes[en.SELF].revised and outcomes[en.SELF].applied == Fraction(4, 5)
    assert not outcomes["edge-a"].revised  # weights were set before the check
    assert hub.ledger.is_verified("edge-a", KIND)
    assert hub.ledger.trust("edge-a", KIND) == Fraction(14, 23)  # (0.9 + 1/2) / 2.3
    assert hub.ledger.entries[-1].reason == "consistency with self"


def test_a_reference_must_be_independent_and_verified():
    ledger = en.SourceLedger(POLICY)
    for n in ("a", "b", "c"):
        ledger.enrol(n, reason="test")
    ledger.declare_group("g", ["a", "b"], reason="shared firmware")
    ledger.record_ground_truth("b", KIND, correct=True, against="setup")
    with pytest.raises(ValueError, match="not independent"):
        ledger.record_consistency("a", KIND, degree=Fraction(1), reference="b")
    with pytest.raises(ValueError, match="not verified"):
        ledger.record_consistency("a", KIND, degree=Fraction(1), reference="c")
    with pytest.raises(ValueError, match="not independent"):
        ledger.record_consistency("a", KIND, degree=Fraction(1), reference="a")


def test_an_inconsistency_lowers_the_record_and_is_kept_as_a_dispute():
    hub, _ = _hub(["edge-a"])
    hub.observe_own(REPORT)
    hub.receive(_packet("edge-a", _distinct_report("odd", p95_change=-40.0)))
    hub.close_round()
    assert hub.disputes == [("edge-a", "derived:odd", en.SELF, DERIVED)]
    assert hub.ledger.trust("edge-a", KIND) < ONE_PASS
    assert hub.ledger.is_verified("edge-a", KIND)  # only ground truth suspends


def test_ground_truth_outranks_consistency():
    ledger = en.SourceLedger(POLICY)
    for n in ("truth", "agree"):
        ledger.enrol(n, reason="test")
    ledger.record_ground_truth("truth", KIND, correct=True, against="reference meter")
    ledger.record_consistency("agree", KIND, degree=Fraction(1), reference=en.SELF)
    assert ledger.trust("truth", KIND) > ledger.trust("agree", KIND)
    with pytest.raises(ValueError, match="outrank"):
        dataclasses.replace(POLICY, ground_truth_weight=Fraction(1, 2),
                            consistency_weight=Fraction(1))


def test_consistency_is_a_degree_weighed_into_the_record():
    ledger = en.SourceLedger(POLICY)
    for n in ("half", "most"):
        ledger.enrol(n, reason="test")
    # Half agreement: 1/2 of the weight to successes, 1/2 (times 2) to failures.
    assert not ledger.record_consistency("half", KIND, degree=Fraction(1, 2), reference=en.SELF)
    assert ledger.trust("half", KIND) == Fraction(23, 51)  # (0.9 + 1/4) / (0.9 + 1/4 + 0.9 + 1/2)
    assert not ledger.is_verified("half", KIND)
    assert ledger.record_consistency("most", KIND, degree=Fraction(3, 4), reference=en.SELF)
    assert ledger.is_verified("most", KIND)
    for bad in (Fraction(-1, 10), Fraction(11, 10)):
        with pytest.raises(ValueError, match="degree"):
            ledger.record_consistency("most", KIND, degree=bad, reference=en.SELF)


def test_where_a_degree_counts_as_agreement_follows_the_failure_multiple():
    # No figure of its own: agreement is where successes outweigh failures.
    assert not POLICY.agrees(Fraction(2, 3)) and POLICY.agrees(Fraction(7, 10))
    even = dataclasses.replace(POLICY, failure_multiple=Fraction(1))
    assert even.agrees(Fraction(3, 5)) and not POLICY.agrees(Fraction(3, 5))
    assert not even.agrees(Fraction(1, 2))


def test_the_p95_degree_falls_as_reports_part():
    def item(change):
        return en.Item("i", KIND, "s", {} if change is None else {"p95_change_pct": change})

    assert CHECK.degree(item(40.0), item(40.0)) == 1
    assert CHECK.degree(item(40.0), item(77.5)) == Fraction(1, 2)  # half the spread apart
    assert CHECK.degree(item(10.0), item(200.0)) == 0  # beyond the spread
    assert CHECK.degree(item(5.0), item(-5.0)) == 0  # moved opposite ways
    assert CHECK.degree(item(5.0), item(None)) is None


def test_a_near_miss_costs_less_than_a_wide_one():
    trust = {}
    for name, offset in (("exact", 0), ("near", 5), ("wide", 20)):
        hub, _ = _hub([name])
        _round(hub, name, 0, OWN_P95 + offset)
        assert hub.ledger.is_verified(name, KIND) and hub.disputes == []  # both agree
        trust[name] = hub.ledger.trust(name, KIND)
    assert trust["wide"] < trust["near"] < trust["exact"]  # no cliff, no free pass


def test_recent_behaviour_counts_most_and_trust_has_a_ceiling():
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("edge-a", reason="test")
    for _ in range(50):
        ledger.record_ground_truth("edge-a", KIND, correct=True, against="meter")
    assert ledger.trust("edge-a", KIND) == POLICY.ceiling
    assert ledger.record_ground_truth("edge-a", KIND, correct=False, against="meter")
    assert ledger.weight("edge-a", KIND) == 0  # one failure suspends at once
    for _ in range(3):
        ledger.record_ground_truth("edge-a", KIND, correct=False, against="meter")
    # A long good run does not cushion a switch: four failures undo fifty passes.
    assert ledger.trust("edge-a", KIND) < Fraction(1, 2)


def test_trust_falls_faster_than_it_rises():
    ledger = en.SourceLedger(POLICY)
    for n in ("up", "down"):
        ledger.enrol(n, reason="test")
    ledger.record_ground_truth("up", KIND, correct=True, against="meter")
    ledger.record_ground_truth("down", KIND, correct=False, against="meter")
    half = Fraction(1, 2)
    assert half - ledger.trust("down", KIND) > ledger.trust("up", KIND) - half


def test_a_verified_source_checked_wrong_is_suspended_and_nothing_recomputed():
    hub, belief_id = _hub(["edge-a"])
    hub.receive(_packet("edge-a"))
    hub.close_round()
    before = hub.memory.get_belief(belief_id)
    review = hub.check_ground_truth("edge-a", DERIVED, correct=False, against="inspection")
    assert review == [belief_id]
    assert not hub.ledger.is_verified("edge-a", KIND)
    assert hub.ledger.entries[-1].action == "suspend"
    assert hub.memory.get_belief(belief_id) == before
    with pytest.raises(ValueError, match="no item"):
        hub.check_ground_truth("edge-a", "never-sent", correct=True, against="x")


# --- figures: none built in ------------------------------------------------------


def test_the_mechanism_has_no_figure_of_its_own():
    with pytest.raises(TypeError):
        en.Policy()  # every figure must be supplied
    with pytest.raises(TypeError):
        en.P95Check()
    with pytest.raises(TypeError):
        en.SourceLedger()
    assert inspect.signature(en.aggregate).parameters["cap"].default is inspect.Parameter.empty
    for name in ("PEER_CAP", "P95_TOLERANCE_PP", "P95_DRIFT_LIMIT_PP"):
        assert not hasattr(en, name)


def test_policy_refuses_settings_that_change_what_the_mechanism_means():
    for change, message in [
        ({"failure_multiple": Fraction(1, 2)}, "fall slower"),
        ({"discount": Fraction(0)}, "discount"),
        ({"ceiling": Fraction(1)}, "ceiling"),
        ({"audit_rate": Fraction(3, 2)}, "audit_rate"),
        ({"audit_rate": Fraction(0)}, "checks never stop"),
        ({"drift_window": 1}, "drift_window"),
        ({"cap": Fraction(0)}, "cap"),
    ]:
        with pytest.raises(ValueError, match=message):
            dataclasses.replace(POLICY, **change)
    with pytest.raises(ValueError, match="positive"):
        en.P95Check(spread_pp=Fraction(0), drift_limit_pp=Fraction(10))


def test_the_same_reports_judged_under_two_policies_give_two_outcomes():
    strict = dataclasses.replace(POLICY, drift_window=3)
    caught = {}
    for name, policy in (("lenient", POLICY), ("strict", strict)):
        hub, _ = _hub(["biased"], policy=policy)
        for n in range(3):
            _round(hub, "biased", n, OWN_P95 + 12)
        caught[name] = _findings(hub, "biased")
    assert caught == {"lenient": [], "strict": ["drift"]}


# --- trust is held per context ------------------------------------------------


def test_a_source_trusted_in_one_context_is_not_trusted_in_another():
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("edge-a", reason="test")
    memory = EpistemicMemory()
    _OPEN.append(memory)
    day = Belief("p95 regressed by day", BeliefType.THEORY, 0.5, "checkout")
    night = Belief("p95 regressed at night", BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(day)
    memory.add_belief(night)
    hub = en.EdgeNode("hub", memory, ledger, [
        en.Route(KIND, day.id, en.p95_rose, context="day"),
        en.Route(KIND, night.id, en.p95_rose, context="night"),
    ])
    ledger.record_ground_truth("edge-a", f"{KIND}@day", correct=True, against="meter")
    hub.receive(_packet("edge-a", signed=False))
    outcomes = {o.belief_id: o for o in hub.close_round()}
    assert outcomes[day.id].revised and outcomes[day.id].applied == ONE_PASS
    assert outcomes[night.id].offered == 0  # a lead at night
    # A failure at night leaves the day record as it was.
    hub.check_ground_truth("edge-a", DERIVED, correct=False, against="night meter",
                           context=f"{KIND}@night")
    assert ledger.trust("edge-a", f"{KIND}@night") < Fraction(1, 2)
    assert ledger.weight("edge-a", f"{KIND}@day") == ONE_PASS
    with pytest.raises(ValueError, match="not routed"):
        hub.check_ground_truth("edge-a", DERIVED, correct=True, against="x", context="dusk")


# --- the covert node: a good record, then a subtle shift ------------------------

OWN_P95 = REPORT["derived"][0]["data"]["p95_change_pct"]


def _round(hub, node, n, p95_change):
    """One round: the hub's own observation, and the source's report at *p95_change*."""
    hub.observe_own(REPORT)
    hub.receive(_packet(node, _distinct_report(f"{node}-{n}", p95_change=p95_change)))
    return hub.close_round()


def _findings(hub, node):
    return [e.reason.split(":")[0] for e in hub.ledger.entries
            if e.node_id == node and e.action == "suspend"]


def test_audits_never_stop_and_ignore_the_record():
    hub, _ = _hub(["good"])
    for _ in range(30):
        hub.ledger.record_ground_truth("good", KIND, correct=True, against="meter")
    fresh, _ = _hub(["new"], verified=False)
    ids = [f"item-{n}" for n in range(400)]
    drawn = [i for i in ids if hub._audit_drawn("good", i)]
    assert drawn == [i for i in ids if fresh._audit_drawn("good", i)]  # record plays no part
    assert 50 < len(drawn) < 110  # about one in five, at a fixed salt
    other_salt = en.EdgeNode("x", hub.memory, hub.ledger, [], audit_salt=b"other")
    assert drawn != [i for i in ids if other_salt._audit_drawn("good", i)]
    hub.receive(_packet("good"))
    assert set(hub.audits) <= {("good", i.item_id) for i in _packet("good").items}


def test_a_source_that_contradicts_itself_is_suspended():
    hub, belief_id = _hub(["edge-a"])
    hub.receive(_packet("edge-a", _distinct_report("first")))
    hub.close_round()
    hub.receive(_packet("edge-a", _distinct_report("second", p95_change=-30.0)))
    hub.close_round()
    assert ("edge-a", "derived:second", "edge-a", "derived:first") in hub.disputes
    assert _findings(hub, "edge-a") == ["self-contradiction"]
    assert hub.ledger.weight("edge-a", KIND) == 0
    assert hub.review == [belief_id]


def test_only_ground_truth_lifts_a_suspension():
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("edge-a", reason="test")
    ledger.record_ground_truth("edge-a", KIND, correct=True, against="meter")
    assert ledger.record_behaviour("edge-a", KIND, finding="drift", detail="test")
    ledger.record_consistency("edge-a", KIND, degree=Fraction(1), reference=en.SELF)
    assert not ledger.is_verified("edge-a", KIND)  # agreement alone does not lift it
    ledger.record_ground_truth("edge-a", KIND, correct=True, against="a person's review")
    assert ledger.is_verified("edge-a", KIND)
    with pytest.raises(ValueError, match="unknown finding"):
        ledger.record_behaviour("edge-a", KIND, finding="rumour", detail="x")


def test_a_slow_drift_is_caught_while_every_single_report_still_passes():
    hub, belief_id = _hub(["drifter"])
    caught_at = None
    for n in range(12):
        _round(hub, "drifter", n, OWN_P95 + 3 * n)  # three points further each round
        if not hub.ledger.is_verified("drifter", KIND):
            caught_at = n
            break
    consistency = [e for e in hub.ledger.entries
                   if e.node_id == "drifter" and e.reason == "consistency with self"]
    assert all(e.passed for e in consistency)  # each report alone looked fine
    assert caught_at is not None
    assert _findings(hub, "drifter") == ["drift"]
    assert hub.review == [belief_id]


def test_a_constant_bias_that_each_check_accepts_is_caught():
    hub, _ = _hub(["biased"])
    for n in range(5):
        _round(hub, "biased", n, OWN_P95 + 12)
    assert _findings(hub, "biased") == ["drift"]


def test_an_honest_noisy_source_is_never_flagged():
    hub, _ = _hub(["honest"])
    for n in range(20):
        _round(hub, "honest", n, OWN_P95 + (8 if n % 2 else -8))
    assert _findings(hub, "honest") == []
    assert hub.ledger.is_verified("honest", KIND)
    assert hub.disputes == []


# --- aggregation -------------------------------------------------------------


def test_matching_reports_from_one_declared_group_count_once():
    nodes = [f"edge-{i}" for i in range(5)]
    hub, belief_id = _hub(nodes, group="same-firmware")
    for n in nodes:
        hub.receive(_packet(n))
    outcomes = hub.close_round()
    assert [o.node_id for o in outcomes if o.revised] == ["edge-0"]  # lowest id on a tie
    assert len(hub.memory.get_revisions(belief_id)) == 1


def test_one_source_flooding_distinct_observations_cannot_pass_its_cap():
    hub, belief_id = _hub(["edge-a"])
    for n in range(20):
        hub.receive(_packet("edge-a", _distinct_report(n)))
        hub.close_round()
    belief = hub.memory.get_belief(belief_id)
    # Uniform prior Beta(1, 1) plus at most the cap of 2 from one group: 3/4 at most.
    assert belief.alpha - 1 <= float(POLICY.cap) + 1e-12
    assert belief.confidence <= 0.75 + 1e-12


def test_independent_groups_each_bring_their_own_cap():
    nodes = [f"edge-{i}" for i in range(4)]
    hub, belief_id = _hub(nodes)
    for n in range(6):
        for node in nodes:
            hub.receive(_packet(node, _distinct_report(f"{node}-{n}")))
        hub.close_round()
    assert hub.memory.get_belief(belief_id).confidence > 0.75


def test_aggregation_is_exact_conserving_and_independent_of_order():
    rng = random.Random(7)  # fixed: the order is what varies, not the result
    offers = [
        en.Offer(f"n{i}", f"g{i % 3}", en.Item(f"item{i}", KIND, "s", {}), "b", i % 2 == 0,
                 Fraction(rng.randint(1, 9), rng.randint(10, 13)))
        for i in range(12)
    ]
    used = {("g0", "b"): Fraction(17, 10)}
    expected, absorbed = en.aggregate(offers, used, POLICY.cap)
    for _ in range(20):
        rng.shuffle(offers)
        assert en.aggregate(offers, used, POLICY.cap) == (expected, absorbed)
    total = sum(o.weight for o in offers)
    assert sum(a.applied for a in expected) + absorbed == total
    assert sum(1 for a in expected if a.applied) == 3  # one per group
    g0 = next(a for a in expected if a.offer.group == "g0" and a.applied)
    assert g0.applied == Fraction(3, 10)  # cut to what remains of the cap of 2


def test_the_package_never_imports_or_runs_hybrid_agent():
    # ADR-0006: episteme gains no dependency on hybrid-agent; the node reads its report.
    tree = ast.parse(Path(en.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    assert not imported & {"hybrid_agent", "subprocess", "socket", "urllib", "http"}


def test_stored_evidence_names_the_node_and_the_context_it_was_weighed_in():
    hub, belief_id = _hub(["edge-a"])
    hub.observe_own(REPORT)
    hub.receive(_packet("edge-a"))
    hub.close_round()
    belief = hub.memory.get_belief(belief_id)
    stored = {(e.node, e.kind) for e in map(hub.memory.get_evidence, belief.evidence_ids)}
    assert stored == {("edge-a", KIND), (en.SELF, KIND)}


# --- refusals and the paths a report can take without moving anything --------


def test_malformed_settings_and_records_are_refused():
    with pytest.raises(ValueError, match="own_reliability"):
        dataclasses.replace(POLICY, own_reliability=Fraction(3, 2))
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("edge-a", reason="test")
    with pytest.raises(ValueError, match="already enrolled"):
        ledger.enrol("edge-a", reason="again")
    with pytest.raises(ValueError, match="needs a reason"):
        ledger.revoke("edge-a", reason="  ")
    offer = en.Offer("edge-a", "g", en.Item("i", KIND, "s", {}), "b", True, Fraction(-1))
    with pytest.raises(ValueError, match="negative weight"):
        en.aggregate([offer], {}, POLICY.cap)


def test_a_finding_on_an_unverified_source_lowers_its_record_and_suspends_nothing():
    ledger = en.SourceLedger(POLICY)
    ledger.enrol("new", reason="test")
    assert not ledger.record_behaviour("new", KIND, finding="drift", detail="test")
    assert ledger.trust("new", KIND) < Fraction(1, 2)
    assert not any(e.action == "suspend" for e in ledger.entries)


def _custom_hub(direction, compare, deviation=None):
    hub, belief_id = _hub(["edge-a"])
    hub.routes = [en.Route(KIND, belief_id, direction)]
    hub.comparators = {KIND: compare}
    hub.deviations = {} if deviation is None else {KIND: (deviation, Fraction(1))}
    hub.observe_own(REPORT)
    hub.receive(_packet("edge-a"))
    return hub, hub.close_round()


def test_an_item_with_no_direction_is_not_offered():
    _, outcomes = _custom_hub(lambda item: None, CHECK.degree)
    assert outcomes == []
    assert en.p95_rose(en.Item("i", KIND, "s", {})) is None


def test_reports_that_cannot_be_compared_leave_the_record_alone():
    hub, _ = _custom_hub(en.p95_rose, lambda a, b: None)
    assert not any(e.reason.startswith("consistency") for e in hub.ledger.entries)
    for deviation in (None, lambda a, b: None):  # no drift measure, or none for this pair
        hub, _ = _custom_hub(en.p95_rose, lambda a, b: Fraction(1), deviation)
        assert hub.ledger.entries[-1].reason == "consistency with self"
        assert hub._drift == {}


def test_the_same_report_at_a_new_weight_is_refused_not_rewritten():
    hub, belief_id = _hub(["edge-a"])
    hub.observe_own(REPORT)
    hub.receive(_packet("edge-a"))
    hub.close_round()  # the consistency check changes edge-a's trust after the award
    revisions = len(hub.memory.get_revisions(belief_id))
    hub.receive(_packet("edge-a"))
    (outcome,) = hub.close_round()
    assert not outcome.revised and "Evidence is immutable" in outcome.reason
    assert len(hub.memory.get_revisions(belief_id)) == revisions


# --- revocation --------------------------------------------------------------


def test_revocation_changes_no_belief_and_lists_those_resting_on_the_node():
    hub, belief_id = _hub(["edge-a"])
    hub.receive(_packet("edge-a"))
    hub.close_round()
    before = hub.memory.get_belief(belief_id)
    hub.ledger.revoke("edge-a", reason="tampered")
    assert hub.memory.get_belief(belief_id) == before
    assert hub.resting_on("edge-a") == [belief_id]
    assert not hub.receive(_packet("edge-a"))
