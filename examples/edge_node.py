"""
A first edge node: a prototype of ADR-0006 and ADR-0007, both still Proposed.

THEORY, not an accepted design. ADR-0006 says nothing is built in the package
until it is accepted, so this lives in ``examples/`` and the ``episteme``
package is unchanged: it gains no module, no dependency on hybrid-agent and no
new write path. What follows is a prototype to make the two proposals concrete
enough to accept, change or reject.

What a node does
----------------
1. **Runs a hybrid-agent locally, rules first.** ``run_hybrid_agent`` starts
   ``python -m hybrid_agent ... --rules-first --json`` as a subprocess on the
   node's own machine and reads its report. Nothing is imported from
   hybrid-agent and it opens no listener (ADR-0006, last bullet).
2. **Sends evidence, not beliefs.** ``packet_from_report`` keeps the report's
   observations and derived results as items, its hypotheses as proposals and
   its unknowns as unknowns, and drops its proposed actions. No belief, no
   confidence and no trust figure leaves a node. The packet is signed.
3. **Admits a peer's packet through the existing rules.** ``EdgeNode.receive``
   refuses a packet from a node nobody enrolled, a revoked node, or one whose
   signature does not verify. Each item that a person-declared ``Route`` says
   bears on a belief becomes an *offer* whose weight is the trust a person set
   for that (node, kind) pair, lowered (never raised) by any reliability the
   node stated itself. Hypotheses become ``Claim`` objects, which are
   proposals and are never stored as beliefs.
4. **Aggregates exactly and deterministically, then caps each peer.**
   ``aggregate`` works in ``fractions.Fraction``, never floating point, and
   sorts every input by identifiers, so the same offers in any order give the
   same awards (the discipline of ``dermot-r-cochran/Voting``, borrowed as an
   idea; no code is shared). Two rules, both from the proposals:

   - **One correlation group, one record per belief per round** (ADR-0007
     section 5). A node no one placed in a group is a group of its own, so a
     single peer sending many distinct observations in one round counts once.
     The highest weight is kept; ties go to the lowest (node, item) id.
   - **A lifetime influence cap per group and belief** (``PEER_CAP``). No one
     group can ever add more weight to one belief, on both sides together,
     than the cap. A belief can only go far on evidence from several groups.

   What is not applied is *absorbed*, and conservation is asserted with
   ``assert`` after every round: weight offered = weight applied + weight
   absorbed, exactly.
5. **Writes only through core and memory.** Awards go through
   ``ExperienceLoop.observe`` like any other observation, so ADR-0001, 0002,
   0003 and 0005 hold unchanged: the core's threshold, its per-record delta
   cap and the append-only store all still apply. The exact weights become
   ``float`` only here, at that boundary, because ``Evidence.reliability`` is
   a float (ADR-0005).

The cryptographic layer
-----------------------
Nothing outside the ``Signer``/``Verifier`` section knows how a packet is
signed. A sender holds a ``Signer``; a person enrols a node by recording its
``Verifier``, which holds only what checking needs (for an asymmetric scheme,
the public key) and whose ``fingerprint`` is what the ledger writes down. The
scheme's name is inside the signed body, so a packet cannot be re-labelled as
another scheme, and a packet in a scheme other than the one enrolled for its
node is refused. A ``Verifier`` also says whether it is ``symmetric`` (its
holder could sign too), and enrolment records that, so the limit of HMAC is
on the record rather than only in this docstring. To add a scheme, write one
class with ``scheme``, ``symmetric``, ``fingerprint``, ``sign`` (sender side)
and ``verify`` (receiver side).

Trust (``TrustLedger``) changes only by an appended entry from a person or a
checked outcome (ADR-0007 section 4). There is no method that takes another
node's agreement, a report count or time online, and the tests pin that.

Guesses (marked ``GUESS`` in the code; each is the author's call)
-----------------------------------------------------------------
- ``DEFAULT_TRUST`` is 0: a pair nobody set has no trust at all. ADR-0007
  leaves open "a figure below 0.5, or zero until a person sets it".
- ``PEER_CAP`` is 2, the same weight as the prior a belief starts from
  (``PRIOR_STRENGTH``). From a uniform prior one group alone can then take a
  belief no further than 0.75. The figure is a guess, not derived.
- The round is the window within which a group counts once. ADR-0007 leaves
  the window open; a round is closed by the caller.
- HMAC-SHA256 is the only signature scheme written. It is in the standard
  library, but the receiver holds the same secret and could forge a packet,
  so a real network needs an asymmetric scheme. Signing and verifying sit
  behind the ``Signer`` and ``Verifier`` interfaces (see *The cryptographic
  layer* below), so one can be added without touching trust or aggregation.
  Which scheme, and which library provides it, is the author's call; none is
  named here (AGENTS.md principle 10).
- Report data that is a list or a mapping travels as a SHA-256 digest, not in
  full, to keep packets small for an edge link. No packet size, latency or
  power figure is claimed or measured.
- A hybrid-agent observation's ``source`` (``deploy_log``, ``metrics``,
  ``diff``, ``compute.compare_windows``) is used as the kind of observation
  that trust is held for.

Usage::

    python examples/edge_node.py /path/to/hybrid-agent

runs hybrid-agent on its worked example twice, as two nodes, and shows a third
node admitting their packets. Without a path it uses the report recorded in
``tests/fixtures/hybrid_agent_rules_first_report.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import ClassVar, Protocol

from episteme import (
    Belief,
    BeliefType,
    Claim,
    EpistemicCore,
    EpistemicMemory,
    ExperienceLoop,
    Observation,
)
from episteme.models import PRIOR_STRENGTH

#: GUESS: trust in a (node, kind) pair nobody has set. Below the core's
#: threshold, so a new pair's reports are recorded and move no belief.
DEFAULT_TRUST = Fraction(0)

#: GUESS: the most weight one correlation group may ever add to one belief,
#: both sides together. Equal to the weight of a new belief's prior.
PEER_CAP = Fraction(PRIOR_STRENGTH).limit_denominator()

#: The question the worked example asks hybrid-agent.
CHECKOUT_QUESTION = "Why did checkout p95 latency go up after the latest deploy?"

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "hybrid_agent_rules_first_report.json"
)


# ----------------------------------------------------------------------
# What crosses between nodes
# ----------------------------------------------------------------------


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class Item:
    """One observation or derived result from the sender's own report."""

    item_id: str
    kind: str
    summary: str
    data: dict
    stated_reliability: Fraction | None = None

    def to_wire(self) -> dict:
        stated = self.stated_reliability
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "summary": self.summary,
            "data": self.data,
            "stated_reliability": None if stated is None else str(stated),
        }


@dataclass(frozen=True)
class Packet:
    """A node's signed report: evidence, proposals and unknowns, no beliefs.

    ``sent_at`` is the sender's own clock, kept as a stated value and never
    used for ordering (ADR-0007 section 6).
    """

    node_id: str
    sent_at: str
    items: tuple[Item, ...]
    hypotheses: tuple[str, ...]
    unknowns: tuple[str, ...]
    scheme: str = ""
    signature: str = ""

    def body(self) -> bytes:
        return _canonical(
            {
                "scheme": self.scheme,
                "node_id": self.node_id,
                "sent_at": self.sent_at,
                "items": [i.to_wire() for i in self.items],
                "hypotheses": list(self.hypotheses),
                "unknowns": list(self.unknowns),
            }
        )


# ----------------------------------------------------------------------
# The cryptographic layer: the only code that knows how a packet is signed
# ----------------------------------------------------------------------


class Signer(Protocol):
    """What a sending node holds: it can produce a signature over a body."""

    @property
    def scheme(self) -> str: ...

    def sign(self, body: bytes) -> str: ...


class Verifier(Protocol):
    """What a person enrols for a node: it can check a signature, and no more.

    ``symmetric`` is True when holding the verifier is enough to sign as
    well, as with HMAC; the receiver could then forge the node's packets.
    ``fingerprint`` identifies the verifying material for the record and
    must not reveal a secret.
    """

    @property
    def scheme(self) -> str: ...

    @property
    def symmetric(self) -> bool: ...

    def fingerprint(self) -> str: ...

    def verify(self, body: bytes, signature: str) -> bool: ...


@dataclass(frozen=True)
class HmacSha256:
    """HMAC-SHA256 over a shared secret: a ``Signer`` and a ``Verifier`` at once.

    GUESS, and a stand-in: it is in the standard library, but it is
    symmetric, so whoever can verify a node's packets can also forge them.
    """

    secret: bytes = field(repr=False)
    scheme: ClassVar[str] = "hmac-sha256"
    symmetric: ClassVar[bool] = True

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("an HMAC secret must not be empty")

    def fingerprint(self) -> str:
        # A digest of a domain-separated input, so the record never holds the
        # secret and the fingerprint is not itself an HMAC of anything.
        return _digest(["fingerprint", self.scheme, self.secret.hex()])

    def sign(self, body: bytes) -> str:
        return hmac.new(self.secret, body, hashlib.sha256).hexdigest()

    def verify(self, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(body), signature)


def sign(packet: Packet, signer: Signer) -> Packet:
    """Return *packet* labelled with *signer*'s scheme and signed by it.

    The scheme is set before signing, so it is covered by the signature.
    """
    labelled = Packet(
        packet.node_id,
        packet.sent_at,
        packet.items,
        packet.hypotheses,
        packet.unknowns,
        scheme=signer.scheme,
    )
    return Packet(
        labelled.node_id,
        labelled.sent_at,
        labelled.items,
        labelled.hypotheses,
        labelled.unknowns,
        scheme=labelled.scheme,
        signature=signer.sign(labelled.body()),
    )


def run_hybrid_agent(
    hybrid_agent_dir: Path, question: str, evidence_dir: Path, *, python: str = sys.executable
) -> dict:
    """Run hybrid-agent locally with ``--rules-first`` and return its JSON report.

    A subprocess, not an import: the node carries hybrid-agent's report and
    does not turn it into a library or a service (ADR-0006).
    """
    done = subprocess.run(
        [
            python,
            "-m",
            "hybrid_agent",
            question,
            "--evidence",
            str(evidence_dir),
            "--rules-first",
            "--json",
        ],
        cwd=hybrid_agent_dir,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(done.stdout)


def packet_from_report(
    node_id: str,
    signer: Signer,
    report: dict,
    *,
    sent_at: str,
    stated: dict[str, Fraction] | None = None,
) -> Packet:
    """Build a signed packet from a hybrid-agent report.

    Observations and derived results become items; hypotheses travel as
    proposals; unknowns stay unknowns; proposed actions are dropped, since
    they are not evidence of anything (ADR-0006). *stated* lets the node
    give a reliability for its own reading of a kind; a receiver will only
    ever use it to lower the weight.

    Raises
    ------
    ValueError
        If the report is not awaiting human review: a report in any other
        state is not one hybrid-agent produced under its own rules.
    """
    if report.get("status") != "awaiting_human_review":
        raise ValueError(f"report status {report.get('status')!r} is not awaiting_human_review")
    stated = stated or {}
    items = tuple(
        Item(
            item_id=e["id"],
            kind=e["source"],
            summary=e["summary"],
            # GUESS: lists and mappings travel as digests, scalars in full.
            data={
                k: (_digest(v) if isinstance(v, (list, dict)) else v)
                for k, v in sorted(e.get("data", {}).items())
            },
            stated_reliability=stated.get(e["source"]),
        )
        for e in [*report.get("observations", []), *report.get("derived", [])]
    )
    hypotheses = tuple(h["statement"] for h in report.get("hypotheses", []))
    unknowns = tuple(report.get("unknowns", []))
    return sign(Packet(node_id, sent_at, items, hypotheses, unknowns), signer)


# ----------------------------------------------------------------------
# Trust: set by people, revised only by checked outcomes (ADR-0007)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TrustEntry:
    """One appended change to trust, enrolment, groups or revocation."""

    action: str
    node_id: str
    by: str
    reason: str
    kind: str = ""
    alpha: Fraction = Fraction(0)
    beta: Fraction = Fraction(0)
    detail: str = ""


class TrustLedger:
    """Append-only record of enrolment, trust, groups and revocation.

    Trust in a (node, kind) pair is the mean of a Beta posterior over checked
    outcomes, started from a prior a person set, in exact fractions. Every
    method that changes it needs a person (``by``) and a reason. There is
    deliberately no method that takes peer agreement, a report count or time.
    """

    def __init__(self) -> None:
        self._entries: list[TrustEntry] = []
        self._verifiers: dict[str, Verifier] = {}
        self._counts: dict[tuple[str, str], tuple[Fraction, Fraction]] = {}
        self._groups: dict[str, str] = {}
        self._revoked: set[str] = set()

    @property
    def entries(self) -> tuple[TrustEntry, ...]:
        return tuple(self._entries)

    def _append(self, entry: TrustEntry) -> None:
        if not entry.by.strip() or not entry.reason.strip():
            raise ValueError("every trust entry needs a person (by) and a reason")
        self._entries.append(entry)

    def enrol(self, node_id: str, verifier: Verifier, *, by: str, reason: str) -> None:
        """Record the node's verifier: its scheme, whether it is symmetric, its fingerprint."""
        if node_id in self._verifiers:
            raise ValueError(f"node {node_id!r} is already enrolled")
        kind = "symmetric" if verifier.symmetric else "asymmetric"
        detail = f"{verifier.scheme} ({kind}) {verifier.fingerprint()}"
        self._append(TrustEntry("enrol", node_id, by, reason, detail=detail))
        self._verifiers[node_id] = verifier

    def set_trust(
        self, node_id: str, kind: str, trust: Fraction, *, by: str, reason: str
    ) -> None:
        """A person sets the trust for a pair, as a prior worth ``PRIOR_STRENGTH``."""
        trust = Fraction(trust)
        if not 0 <= trust <= 1:
            raise ValueError(f"trust must be in [0, 1], got {trust}")
        strength = Fraction(PRIOR_STRENGTH).limit_denominator()
        alpha, beta = trust * strength, (1 - trust) * strength
        self._append(TrustEntry("set", node_id, by, reason, kind, alpha, beta))
        self._counts[(node_id, kind)] = (alpha, beta)

    def record_check(
        self, node_id: str, kind: str, *, correct: bool, against: str, by: str
    ) -> None:
        """Record an independent check of one of the pair's reports.

        *against* names what the report was checked against (a person's
        inspection, a reference instrument, a later ground truth). A check on
        a pair nobody has set is refused: there is no prior to revise.
        """
        if (node_id, kind) not in self._counts:
            raise ValueError(f"no trust set for ({node_id!r}, {kind!r}); a person sets it first")
        alpha, beta = self._counts[(node_id, kind)]
        alpha, beta = (alpha + 1, beta) if correct else (alpha, beta + 1)
        verdict = "right" if correct else "wrong"
        self._append(TrustEntry("check", node_id, by, f"{verdict} against {against}",
                                kind, alpha, beta))
        self._counts[(node_id, kind)] = (alpha, beta)

    def declare_group(self, group: str, node_ids: Iterable[str], *, by: str, reason: str) -> None:
        """Declare nodes that share a cause (sensor, firmware, model, site)."""
        for node_id in node_ids:
            self._append(TrustEntry("group", node_id, by, reason, detail=group))
            self._groups[node_id] = group

    def revoke(self, node_id: str, *, by: str, reason: str) -> None:
        self._append(TrustEntry("revoke", node_id, by, reason))
        self._revoked.add(node_id)

    def verifier(self, node_id: str) -> Verifier | None:
        return self._verifiers.get(node_id)

    def is_revoked(self, node_id: str) -> bool:
        return node_id in self._revoked

    def trust(self, node_id: str, kind: str) -> Fraction:
        counts = self._counts.get((node_id, kind))
        if counts is None:
            return DEFAULT_TRUST
        alpha, beta = counts
        return alpha / (alpha + beta)

    def group(self, node_id: str) -> str:
        """The node's declared group, or a group of its own."""
        return self._groups.get(node_id, f"node:{node_id}")


# ----------------------------------------------------------------------
# Exact, deterministic aggregation with a per-group cap
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    """A person's declaration that items of *kind* bear on *belief_id*.

    *direction* reads an item and returns True (supports), False (counts
    against) or None (does not bear on it).
    """

    kind: str
    belief_id: str
    direction: Callable[[Item], bool | None]


@dataclass(frozen=True)
class Offer:
    node_id: str
    group: str
    item: Item
    belief_id: str
    supporting: bool
    weight: Fraction


@dataclass(frozen=True)
class Award:
    offer: Offer
    applied: Fraction
    reason: str


def _offer_key(o: Offer) -> tuple:
    return (o.belief_id, o.group, o.node_id, o.item.item_id, o.supporting)


def aggregate(
    offers: Iterable[Offer], used: dict[tuple[str, str], Fraction], cap: Fraction = PEER_CAP
) -> tuple[list[Award], Fraction]:
    """Turn one round's offers into awards, exactly and in a fixed order.

    *used* is the weight each (group, belief) has already had applied in
    earlier rounds; it is read, not changed. Returns the awards, sorted by
    identifiers, and the total weight absorbed.

    Per (belief, group) only the highest-weight offer is kept, ties to the
    lowest (node, item) id: a group counts once per belief per round,
    whichever side its records are on. The kept offer is then cut to what
    remains of the group's cap on that belief.
    """
    ordered = sorted(offers, key=_offer_key)
    by_group: dict[tuple[str, str], list[Offer]] = {}
    for o in ordered:
        if o.weight < 0:
            raise ValueError(f"negative weight on offer {o.item.item_id!r}")
        by_group.setdefault((o.belief_id, o.group), []).append(o)

    awards: list[Award] = []
    absorbed = Fraction(0)
    for (belief_id, group), members in sorted(by_group.items()):
        best = min(members, key=lambda o: (-o.weight, o.node_id, o.item.item_id))
        for o in members:
            if o is not best:
                awards.append(Award(o, Fraction(0), f"counted once: group {group} already offers"))
                absorbed += o.weight
        remaining = max(Fraction(0), cap - used.get((group, belief_id), Fraction(0)))
        applied = min(best.weight, remaining)
        reason = "within cap" if applied == best.weight else f"cut to the cap of group {group}"
        awards.append(Award(best, applied, reason))
        absorbed += best.weight - applied

    offered = sum((o.weight for o in ordered), Fraction(0))
    applied_total = sum((a.applied for a in awards), Fraction(0))
    # Conservation, exactly: nothing is created or lost between offer and award.
    assert offered == applied_total + absorbed, (offered, applied_total, absorbed)
    awards.sort(key=lambda a: _offer_key(a.offer))
    return awards, absorbed


# ----------------------------------------------------------------------
# The node
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """What happened to one item: refused, absorbed, or offered to the core."""

    node_id: str
    item_id: str
    belief_id: str
    supporting: bool
    offered: Fraction
    applied: Fraction
    revised: bool
    reason: str


@dataclass
class EdgeNode:
    """A node's receiving side: its own store, its trust ledger and its routes."""

    node_id: str
    memory: EpistemicMemory
    ledger: TrustLedger
    routes: list[Route]
    core: EpistemicCore = field(default_factory=EpistemicCore)
    claims: list[Claim] = field(default_factory=list)
    unknowns: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    _pending: list[Offer] = field(default_factory=list)
    _used: dict[tuple[str, str], Fraction] = field(default_factory=dict)
    _evidence_from: dict[str, str] = field(default_factory=dict)

    def receive(self, packet: Packet) -> bool:
        """Check a peer's packet and queue its offers for the round.

        Returns False, with the reason in ``refused``, if the packet is
        refused whole: unenrolled, revoked, signed in a scheme other than
        the one enrolled, or a signature that fails.
        """
        verifier = self.ledger.verifier(packet.node_id)
        if verifier is None:
            self.refused.append((packet.node_id, "not enrolled"))
            return False
        if self.ledger.is_revoked(packet.node_id):
            self.refused.append((packet.node_id, "revoked"))
            return False
        if packet.scheme != verifier.scheme:
            self.refused.append(
                (packet.node_id, f"scheme {packet.scheme!r} is not the enrolled {verifier.scheme!r}")
            )
            return False
        if not verifier.verify(packet.body(), packet.signature):
            self.refused.append((packet.node_id, "signature does not verify"))
            return False

        group = self.ledger.group(packet.node_id)
        for item in packet.items:
            trust = self.ledger.trust(packet.node_id, item.kind)
            stated = item.stated_reliability
            # A node may lower its own weight, never raise it (ADR-0007 s. 2).
            weight = trust if stated is None else min(trust, Fraction(stated))
            for route in self.routes:
                if route.kind != item.kind:
                    continue
                direction = route.direction(item)
                if direction is None:
                    continue
                self._pending.append(
                    Offer(packet.node_id, group, item, route.belief_id, direction, weight)
                )
        for text in packet.hypotheses:
            # A hypothesis is a proposal, never a belief (ADR-0006).
            self.claims.append(Claim(text=text, type=BeliefType.THEORY,
                                     source=f"node:{packet.node_id}"))
        for text in packet.unknowns:
            self.unknowns.append((packet.node_id, text))
        return True

    def close_round(self) -> list[Outcome]:
        """Aggregate the round's offers and apply the awards through the loop."""
        awards, _ = aggregate(self._pending, self._used)
        self._pending = []
        loop = ExperienceLoop(self.core, self.memory)
        outcomes: list[Outcome] = []
        for award in awards:
            o = award.offer
            if award.applied == 0:
                outcomes.append(Outcome(o.node_id, o.item.item_id, o.belief_id, o.supporting,
                                        o.weight, award.applied, False, award.reason))
                continue
            observation = Observation(
                content=f"{o.item.kind}: {o.item.summary} [{o.item.item_id}]",
                source=f"node:{o.node_id}",
                reliability=float(award.applied),
            )
            try:
                (result,) = loop.observe(observation, [o.belief_id], supporting=o.supporting)
            except ValueError as exc:
                # The same record at another weight: evidence is immutable.
                outcomes.append(Outcome(o.node_id, o.item.item_id, o.belief_id, o.supporting,
                                        o.weight, award.applied, False, str(exc)))
                continue
            if result.revised:
                key = (o.group, o.belief_id)
                self._used[key] = self._used.get(key, Fraction(0)) + award.applied
                if result.evidence_id is not None:
                    self._evidence_from[result.evidence_id] = o.node_id
            outcomes.append(Outcome(o.node_id, o.item.item_id, o.belief_id, o.supporting,
                                    o.weight, award.applied, result.revised, result.reason))
        return outcomes

    def resting_on(self, node_id: str) -> list[str]:
        """Belief ids holding evidence from *node_id*, for a person to review.

        Revocation changes no belief (ADR-0007 section 7); this only lists.
        """
        ids = {e for e, n in self._evidence_from.items() if n == node_id}
        return sorted(
            b.id
            for b in self.memory.list_beliefs()
            if b.id is not None and ids & {*b.evidence_ids, *b.counter_evidence_ids}
        )


# ----------------------------------------------------------------------
# Worked example
# ----------------------------------------------------------------------


def p95_rose(item: Item) -> bool | None:
    """Route rule: a before/after comparison supports a p95 regression if p95 rose."""
    change = item.data.get("p95_change_pct")
    if not isinstance(change, (int, float)):
        return None
    return change > 0


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("hybrid_agent", nargs="?", type=Path,
                        help="a checkout of dermot-r-cochran/hybrid-agent, installed")
    args = parser.parse_args(argv)

    if args.hybrid_agent is None:
        report = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source = f"recorded report ({FIXTURE.name})"
    else:
        evidence = args.hybrid_agent / "examples" / "checkout_latency"
        report = run_hybrid_agent(args.hybrid_agent, CHECKOUT_QUESTION, evidence)
        source = f"hybrid-agent --rules-first in {args.hybrid_agent}"

    keys = {n: HmacSha256(f"secret-{n}".encode()) for n in ("edge-a", "edge-b", "edge-c")}
    ledger = TrustLedger()
    for node_id in ("edge-a", "edge-b"):
        ledger.enrol(node_id, keys[node_id], by="Dermot", reason="worked example")
    ledger.set_trust("edge-a", "compute.compare_windows", Fraction(4, 5),
                     by="Dermot", reason="worked example")
    ledger.set_trust("edge-b", "compute.compare_windows", Fraction(3, 5),
                     by="Dermot", reason="worked example")
    ledger.declare_group("same-firmware", ["edge-a", "edge-b"],
                         by="Dermot", reason="same build and the same metrics source")

    memory = EpistemicMemory()
    belief = Belief("checkout p95 latency regressed after deploy 4.12.0",
                    BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(belief)
    assert belief.id is not None
    hub = EdgeNode("hub", memory, ledger,
                   [Route("compute.compare_windows", belief.id, p95_rose)])

    lines = [f"report: {source}"]
    for node_id in ("edge-a", "edge-b", "edge-c"):
        accepted = hub.receive(
            packet_from_report(node_id, keys[node_id], report, sent_at="2026-11-22T20:00:00Z")
        )
        lines.append(f"{node_id}: packet {'accepted' if accepted else 'refused'}")
    for node_id, why in hub.refused:
        lines.append(f"refused {node_id}: {why}")
    for o in hub.close_round():
        lines.append(f"{o.node_id} {o.item_id}: offered {o.offered}, applied {o.applied}, "
                     f"revised {o.revised} ({o.reason})")
    after = memory.get_belief(belief.id)
    assert after is not None
    lines.append(f"belief: confidence {after.confidence:.3f}, "
                 f"revisions {len(memory.get_revisions(belief.id))}")
    lines.append(f"proposals held, not believed: {len(hub.claims)}")
    lines.append(f"unknowns carried: {len(hub.unknowns)}")
    memory.close()
    return "\n".join(lines)


if __name__ == "__main__":
    print(main())
