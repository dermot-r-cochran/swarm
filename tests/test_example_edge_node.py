"""
Tests for examples/edge_node.py, the edge-node prototype of ADR-0006 and
ADR-0007 (both Proposed).

They are the guards those two records name as likely, written against the
prototype so the proposals can be judged on running code: a node's hypothesis
is never stored as a belief, matching reports from correlated nodes count once,
a pair at the default trust moves no belief, a node cannot raise its own
weight, peer agreement never changes trust, one group's influence on a belief
is capped, aggregation is exact and order-independent, and revocation changes
no belief. The example is outside ``--cov=episteme``; these do not count
towards the coverage ratchet.
"""

import hashlib
import importlib.util
import json
import random
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from episteme import Belief, BeliefType, EpistemicMemory

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "edge_node.py"
REPORT = json.loads(
    (ROOT / "tests" / "fixtures" / "hybrid_agent_rules_first_report.json").read_text(
        encoding="utf-8"
    )
)
KIND = "compute.compare_windows"


def _load():
    spec = importlib.util.spec_from_file_location("edge_node_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["edge_node_example"] = module
    spec.loader.exec_module(module)
    return module


en = _load()


_OPEN: list[EpistemicMemory] = []


@pytest.fixture(autouse=True)
def _close_stores():
    yield
    while _OPEN:
        _OPEN.pop().close()


def _hub(nodes, *, trust=Fraction(4, 5), group=None):
    """A receiving node with one belief at the uniform prior and *nodes* enrolled."""
    ledger = en.TrustLedger()
    for node_id in nodes:
        ledger.enrol(node_id, en.HmacSha256(node_id.encode()), by="tester", reason="test")
        if trust is not None:
            ledger.set_trust(node_id, KIND, trust, by="tester", reason="test")
    if group:
        ledger.declare_group(group, nodes, by="tester", reason="test")
    memory = EpistemicMemory()
    _OPEN.append(memory)
    belief = Belief("p95 regressed", BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(belief)
    hub = en.EdgeNode("hub", memory, ledger, [en.Route(KIND, belief.id, en.p95_rose)])
    return hub, belief.id


def _packet(node_id, report=REPORT, **kw):
    return en.packet_from_report(
        node_id, en.HmacSha256(node_id.encode()), report, sent_at="t", **kw
    )


def _distinct_report(n):
    """A report whose one derived result has a distinct id, so it is new evidence."""
    report = json.loads(json.dumps(REPORT))
    report["derived"][0]["id"] = f"derived:{n}"
    report["derived"][0]["summary"] = f"comparison {n}"
    return report


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
    forged = en.sign(_packet("edge-a"), en.HmacSha256(b"not-the-key"))
    assert not hub.receive(forged)
    hub.ledger.revoke("edge-b", by="tester", reason="device lost")
    assert not hub.receive(_packet("edge-b"))
    assert [why for _, why in hub.refused] == [
        "not enrolled",
        "integrity: signature does not verify",
        "revoked",
    ]
    assert hub.close_round() == []


def test_a_hypothesis_is_held_as_a_claim_and_never_stored_as_a_belief():
    hub, belief_id = _hub(["edge-a"])
    before = [b.id for b in hub.memory.list_beliefs()]
    hub.receive(_packet("edge-a"))
    hub.close_round()
    assert [b.id for b in hub.memory.list_beliefs()] == before == [belief_id]
    assert [c.text for c in hub.claims] == [h["statement"] for h in REPORT["hypotheses"]]
    assert all(c.source == "node:edge-a" for c in hub.claims)


def test_a_pair_at_the_default_trust_moves_no_belief():
    hub, belief_id = _hub(["edge-a"], trust=None)
    hub.receive(_packet("edge-a"))
    (outcome,) = hub.close_round()
    assert outcome.offered == en.DEFAULT_TRUST
    assert not outcome.revised
    assert hub.memory.get_belief(belief_id).confidence == 0.5
    assert hub.memory.get_revisions(belief_id) == []


def test_a_node_can_lower_its_own_weight_but_never_raise_it():
    hub, _ = _hub(["low", "high"], trust=Fraction(3, 5))
    hub.receive(_packet("low", stated={KIND: Fraction(1, 2)}))
    hub.receive(_packet("high", stated={KIND: Fraction(1)}))
    offered = {o.node_id: o.offered for o in hub.close_round()}
    assert offered == {"low": Fraction(1, 2), "high": Fraction(3, 5)}


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
    hub.ledger.enrol("edge-t", _ToyScheme(b"t"), by="tester", reason="test")
    hub.ledger.set_trust("edge-t", KIND, Fraction(4, 5), by="tester", reason="test")
    packet = en.packet_from_report("edge-t", _ToyScheme(b"t"), REPORT, sent_at="t")
    assert packet.scheme == "toy-sha256"
    assert hub.receive(packet)
    (outcome,) = hub.close_round()
    assert outcome.revised and outcome.applied == Fraction(4, 5)
    assert hub.memory.get_belief(belief_id).confidence > 0.5
    assert hub.ledger.entries[0].detail == "toy-sha256 (asymmetric) toy:74"


def test_a_packet_in_a_scheme_other_than_the_enrolled_one_is_refused():
    hub, _ = _hub(["edge-a"])
    relabelled = en.sign(_packet("edge-a"), _ToyScheme(b"edge-a"))
    assert not hub.receive(relabelled)
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
    ledger = en.TrustLedger()
    ledger.enrol("edge-a", en.HmacSha256(b"s3cret"), by="tester", reason="test")
    (entry,) = ledger.entries
    assert entry.detail.startswith("hmac-sha256 (symmetric) sha256:")
    assert b"s3cret".hex() not in entry.detail and "s3cret" not in repr(en.HmacSha256(b"s3cret"))
    with pytest.raises(ValueError, match="must not be empty"):
        en.HmacSha256(b"")


# --- trust does not rest on signatures ----------------------------------------


def test_a_signature_never_changes_an_items_weight():
    ledger = en.TrustLedger()
    ledger.enrol("signed", en.HmacSha256(b"k"), by="tester", reason="test")
    ledger.enrol("unsigned", by="tester", reason="test")
    for node in ("signed", "unsigned"):
        ledger.set_trust(node, KIND, Fraction(3, 5), by="tester", reason="test")
    memory = EpistemicMemory()
    _OPEN.append(memory)
    belief = Belief("p95 regressed", BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(belief)
    hub = en.EdgeNode("hub", memory, ledger, [en.Route(KIND, belief.id, en.p95_rose)])
    assert hub.receive(en.packet_from_report("signed", en.HmacSha256(b"k"), REPORT, sent_at="t"))
    assert hub.receive(en.packet_from_report("unsigned", None, REPORT, sent_at="t"))
    assert hub.received == [("signed", "verified"), ("unsigned", "unchecked")]
    offered = {o.node_id: (o.offered, o.applied) for o in hub.close_round()}
    assert offered["signed"] == offered["unsigned"] == (Fraction(3, 5), Fraction(3, 5))


def test_a_node_enrolled_with_a_verifier_must_pass_its_integrity_check():
    hub, _ = _hub(["edge-a"])
    unsigned = en.packet_from_report("edge-a", None, REPORT, sent_at="t")
    assert unsigned.signature == "" and unsigned.scheme == ""
    assert not hub.receive(unsigned)
    assert hub.refused == [("edge-a", "integrity: scheme '' is not the enrolled 'hmac-sha256'")]


def test_enrolment_without_a_verifier_gives_no_trust():
    ledger = en.TrustLedger()
    ledger.enrol("edge-a", by="tester", reason="test")
    assert ledger.is_enrolled("edge-a") and ledger.verifier("edge-a") is None
    assert ledger.entries[0].detail == "no integrity check"
    assert ledger.trust("edge-a", KIND) == en.DEFAULT_TRUST


def test_an_impostor_using_an_enrolled_id_is_bounded_by_the_cap_and_by_checks():
    ledger = en.TrustLedger()
    ledger.enrol("edge-a", by="tester", reason="test")  # no integrity check: ids can be claimed
    ledger.set_trust("edge-a", KIND, Fraction(1), by="tester", reason="test")
    memory = EpistemicMemory()
    _OPEN.append(memory)
    belief = Belief("p95 regressed", BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(belief)
    hub = en.EdgeNode("hub", memory, ledger, [en.Route(KIND, belief.id, en.p95_rose)])
    for n in range(20):
        forged = en.packet_from_report("edge-a", None, _distinct_report(f"x{n}"), sent_at="t")
        assert hub.receive(forged)
        hub.close_round()
    assert memory.get_belief(belief.id).confidence <= 0.75 + 1e-12
    ledger.record_check("edge-a", KIND, correct=False, against="inspection", by="tester")
    assert ledger.trust("edge-a", KIND) < 1


# --- trust -------------------------------------------------------------------


def test_peer_agreement_never_changes_trust():
    nodes = [f"edge-{i}" for i in range(10)]
    hub, _ = _hub(nodes, trust=Fraction(3, 5))
    entries = hub.ledger.entries
    for round_ in range(3):
        for n in nodes:
            hub.receive(_packet(n, _distinct_report(f"{n}-{round_}")))
        hub.close_round()
    assert hub.ledger.entries == entries
    assert {hub.ledger.trust(n, KIND) for n in nodes} == {Fraction(3, 5)}


def test_trust_moves_only_with_checked_outcomes_by_exact_beta_mean():
    ledger = en.TrustLedger()
    ledger.set_trust("edge-a", KIND, Fraction(1, 2), by="tester", reason="enrolled")
    ledger.record_check("edge-a", KIND, correct=True, against="reference meter", by="tester")
    ledger.record_check("edge-a", KIND, correct=True, against="reference meter", by="tester")
    ledger.record_check("edge-a", KIND, correct=False, against="inspection", by="tester")
    assert ledger.trust("edge-a", KIND) == Fraction(3, 5)  # Beta(1+2, 1+1)
    assert [e.action for e in ledger.entries] == ["set", "check", "check", "check"]


def test_trust_changes_need_a_person_a_reason_and_a_prior():
    ledger = en.TrustLedger()
    with pytest.raises(ValueError, match="person"):
        ledger.set_trust("edge-a", KIND, Fraction(1, 2), by="", reason="x")
    with pytest.raises(ValueError, match="a person sets it first"):
        ledger.record_check("edge-a", KIND, correct=True, against="x", by="tester")
    with pytest.raises(ValueError, match="in \\[0, 1\\]"):
        ledger.set_trust("edge-a", KIND, Fraction(3, 2), by="tester", reason="x")


# --- aggregation -------------------------------------------------------------


def test_matching_reports_from_one_declared_group_count_once():
    nodes = [f"edge-{i}" for i in range(5)]
    hub, belief_id = _hub(nodes, group="same-firmware")
    for n in nodes:
        hub.receive(_packet(n))
    outcomes = hub.close_round()
    assert [o.node_id for o in outcomes if o.revised] == ["edge-0"]  # lowest id on a tie
    assert len(hub.memory.get_revisions(belief_id)) == 1


def test_one_peer_flooding_distinct_observations_cannot_pass_its_cap():
    hub, belief_id = _hub(["edge-a"], trust=Fraction(1))
    for n in range(20):
        hub.receive(_packet("edge-a", _distinct_report(n)))
        hub.close_round()
    belief = hub.memory.get_belief(belief_id)
    # Uniform prior Beta(1, 1) plus at most PEER_CAP from one group: 3/4 at most.
    assert belief.alpha - 1 <= float(en.PEER_CAP) + 1e-12
    assert belief.confidence <= 0.75 + 1e-12


def test_independent_groups_each_bring_their_own_cap():
    nodes = [f"edge-{i}" for i in range(4)]
    hub, belief_id = _hub(nodes, trust=Fraction(1))
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
    expected, absorbed = en.aggregate(offers, used)
    for _ in range(20):
        rng.shuffle(offers)
        assert en.aggregate(offers, used) == (expected, absorbed)
    total = sum(o.weight for o in offers)
    assert sum(a.applied for a in expected) + absorbed == total
    assert sum(1 for a in expected if a.applied) == 3  # one per group
    g0 = next(a for a in expected if a.offer.group == "g0" and a.applied)
    assert g0.applied == Fraction(3, 10)  # cut to what remains of the cap of 2


# --- revocation --------------------------------------------------------------


def test_revocation_changes_no_belief_and_lists_those_resting_on_the_node():
    hub, belief_id = _hub(["edge-a"])
    hub.receive(_packet("edge-a"))
    hub.close_round()
    before = hub.memory.get_belief(belief_id)
    hub.ledger.revoke("edge-a", by="tester", reason="tampered")
    assert hub.memory.get_belief(belief_id) == before
    assert hub.resting_on("edge-a") == [belief_id]
    assert not hub.receive(_packet("edge-a"))


# --- the worked example and the crossing ---------------------------------------


def test_worked_example_from_the_recorded_report():
    lines = en.main([]).splitlines()
    assert "refused edge-c: not enrolled" in lines
    assert any("edge-b" in line and "counted once" in line for line in lines)
    assert lines[-3] == "belief: confidence 0.643, revisions 1"
    assert lines[-2] == "proposals held, not believed: 2"


def test_runs_hybrid_agent_live_when_installed():
    pytest.importorskip("hybrid_agent")
    import hybrid_agent

    checkout = Path(hybrid_agent.__file__).resolve().parents[1]
    report = en.run_hybrid_agent(
        checkout, en.CHECKOUT_QUESTION, checkout / "examples" / "checkout_latency"
    )
    assert not any(step["called_model"] for step in report["trace"])
    assert _packet("edge-a", report).items == _packet("edge-a").items
