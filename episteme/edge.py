"""
The edge node: ADR-0006 and ADR-0007, accepted on 23 November 2026.

A node's receiving side, and the packet it reads from a hybrid-agent report.
It gains the package no dependency: hybrid-agent is run as a separate program
(``examples/edge_node.py`` shows how) and only its JSON report is read here.
Nothing here writes a belief except through ``ExperienceLoop``, that is core
then memory (ADR-0001, ADR-0003). This module is reached as ``episteme.edge``
and is not re-exported from the package root, since names such as ``Policy``,
``Route`` and ``sign`` mean something only here.

What a node does
----------------
1. **Runs a hybrid-agent locally, rules first.** The node runs
   ``python -m hybrid_agent ... --rules-first --json`` on its own machine and
   reads its report (``examples/edge_node.py``'s ``run_hybrid_agent``).
   Nothing is imported from hybrid-agent and it opens no listener (ADR-0006,
   last bullet).
2. **Sends evidence, not beliefs.** ``packet_from_report`` keeps the report's
   observations and derived results as items, its hypotheses as proposals and
   its unknowns as unknowns, and drops its proposed actions. No belief, no
   confidence and no trust figure leaves a node. The packet may be signed, as
   an integrity check only (see *Trust does not rest on signatures*).
3. **Admits a peer's packet through the existing rules.** ``EdgeNode.receive``
   refuses a packet from a node nobody enrolled or a revoked node, and, where
   a person enrolled a verifier for the node, one that fails its integrity
   check. Each item that a person-declared ``Route`` says
   bears on a belief becomes an *offer* whose weight is the receiving node's
   own record of that (source, kind) pair (see *What trust rests on*), lowered
   (never raised) by any reliability the source stated itself. A source not
   yet verified for the kind sends leads: offered at no weight. Hypotheses become ``Claim`` objects, which are
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
   - **A lifetime influence cap per group and belief** (``Policy.cap``). No one
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

Trust does not rest on signatures
---------------------------------
The author's principle (22-23 November 2026): *"Trust is not based on
cryptographic signatures - key management is a weak link."* So:

- **Weight never depends on a signature.** An item's weight comes from the
  receiving node's own record of its source. A verified signature adds nothing
  to it, and an unsigned packet loses nothing by it; a test pins that the two
  get the same weight.
- **A signature is an optional integrity check.** A person may enrol a
  ``Verifier`` for a node; then that node's packets must verify, and one that
  does not is refused as damaged or tampered, the way a malformed packet
  would be. A node enrolled without one is admitted unsigned, and each
  received packet is recorded as ``verified`` or ``unchecked``.
- **A node id in a packet is a claim, not a proof.** Without a verifier,
  anyone who can reach the receiver can claim an enrolled id; with one, a
  stolen or mismanaged key does the same. Neither is assumed away. What
  bounds the damage is what does not rest on keys: a pair's trust is only
  what its behaviour has earned on this node's own checks, one group adds at most
  ``Policy.cap`` to any belief, the core moves a belief at most
  ``max_confidence_delta`` per record, and a report later checked wrong
  lowers the pair's trust. That bound is THEORY, pinned for the cap by a test,
  not a measured resistance to any attack.

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
and ``verify`` (receiver side). Nothing in trust or aggregation reads a
signature.

What trust rests on
-------------------
The author's rulings (23 November 2026): *"Neither is peer trust reliable"*,
and trust rests on *"behaviour over time and consistency with other data
sources."* Each node keeps its own record of every source (``SourceLedger``);
nothing in it is copied from a peer, and no person sets a figure in it.

- **Behaviour over time.** A (source, kind) pair's trust is the mean of a
  Beta record of how its reports held up, starting neutral at Beta(1, 1)
  (ADR-0007 s. 3). Both counts are discounted at each new outcome, so recent
  behaviour counts most; a failure weighs more than a pass; trust stays under
  a ceiling (ADR-0007 s. 8).
- **Consistency with other data sources.** Each round, a source's items are
  compared with references on the same belief and kind: the node's own
  observations (``observe_own``) and sources verified at the start of the
  round, in another correlation group. Each independent group counts once. A
  match is a pass, a mismatch a failure, and the mismatch is kept as a
  dispute. A source cannot be raised by sources nobody has checked, so
  agreement among unverified peers verifies nothing.
- **Ground truth outranks consistency.** A ground-truth check
  (``check_ground_truth``) weighs more than a consistency check, so a lone
  source that turns out right is not out-voted. Only ground truth suspends:
  a verified source checked wrong returns to unverified at once, and the
  beliefs holding its evidence are listed for review, none recomputed.
- **Verified before weighted.** A new pair is unverified and sends leads. It
  becomes verified by a passed check of either kind; a suspended pair only by
  a passed ground-truth check.
- **Per context, never one score.** *"They might be semi-trusted in one
  context but less so in another"* (the author, 23 November 2026). A record is
  held per (source, context), where a context is the kind of observation,
  narrowed by a ``Route``'s ``context`` (a site, a time of day, a load regime)
  where one is declared. A record earned in one context gives nothing in
  another, and a failure in one leaves the others as they were.

The covert node
---------------
*"A covert node or agent may pretend to be good then shift its behaviour in
subtle ways, behaving in malicious ways or even accidentally contradicting
itself"* (the author, 23 November 2026). The design assumes any source may do
this, and a good record buys no exemption from any of the following:

- **Checks never stop.** Every round each source's items are compared with
  independent references, however long its record. And each received item is
  drawn for a ground-truth audit by lot, at ``audit_rate``, after arrival,
  with a keyed hash the source cannot predict and that ignores the record
  (``audits`` is the queue for a person or instrument to work through).
- **Self-contradiction.** A source's new item on a belief is compared with
  what it said before on the same belief, in the same context. A
  contradiction is kept as a dispute and suspends a verified source.
- **Slow drift.** Each report can agree well enough with its reference while
  all of them lean one way. The node averages a source's signed deviations
  from independent references over ``drift_window`` reports, and a mean
  beyond the kind's limit is drift: it suspends a verified source.
- **Trust falls faster than it rises.** A failure weighs ``failure_multiple`` passes, every
  outcome discounts the history, trust has a ceiling, and a suspension lists
  the beliefs holding the source's evidence for review, none recomputed.

What this does not claim: a source that lies rarely, only where nothing
independent can be compared, or drifts more slowly than the window can see,
may go unnoticed for a time; how long is unmeasured.

People enrol names, declare correlation groups and revoke; none of those is
a figure. There is no method that takes a person's figure, a peer's vouching,
a signature, a report count or time online, and the tests pin that.

Open risk, stated rather than solved: sources sharing a cause nobody declared
can look consistent with each other; consistency then overstates agreement.

Figures: none built in
----------------------
*"If the figures are arbitrary then they are either fuzzy or should be
abstracted out"* (the author, 23 November 2026). Every figure the mechanism
uses is abstracted out: ``Policy`` (check weights, failure multiple,
discount, ceiling, own reliability, cap, audit rate, drift window) and
``P95Check`` (spread and drift limit) have no defaults, and a node that
builds one must supply each. ``Policy`` refuses only settings that would make
the mechanism mean something else, such as consistency outranking ground
truth or trust falling slower than it rises. The figures in the example's ``main`` are
its inputs, not the node's. ``NEUTRAL``, Beta(1, 1), is not one
of them: it is the author's ruling that a new source is neutral (ADR-0007
s. 3).

Consistency is a degree, not a pass or a fail
---------------------------------------------
A comparator returns how far two reports agree, a degree from 0 (not at all)
to 1 (fully), or None where they cannot be compared. A crisp tolerance would
be one more arbitrary figure with a cliff at its edge, where a report one
point inside counts in full and one point outside counts against. Instead a
check of degree *d* adds ``d`` of its weight to the source's successes and
``1 - d`` to its failures (times ``failure_multiple``), so a near miss costs
a little and a wide one costs a lot.

Some steps still need a yes or a no: whether a check verifies a new pair,
and whether it is a dispute or a self-contradiction. Those use no new figure.
A degree *agrees* when what it adds to the successes outweighs what it adds
to the failures, ``d > failure_multiple * (1 - d)``; with a failure multiple
of 2 that is above 2/3. The cut follows from how heavily the node already
weighs a failure, so a node that is harder on failures is harder to agree
with.

How the degree is drawn from the data is the comparator's, and a node
supplies its own. ``P95Check.degree`` is the worked example's: 0 if the two
moved opposite ways, otherwise falling in a straight line from 1 at equal
changes to 0 at ``spread_pp`` apart. The straight line is a guess; any shape
that gives 1 for identical reports and falls as they part would serve.

Design guesses (marked ``GUESS`` in the code; each is the author's call)
-----------------------------------------------------------------------
- A passed consistency check verifies a new pair, as a passed ground-truth
  check does. Self-contradiction and drift suspend a verified source, as a
  failed ground-truth check does; a single inconsistency with another source
  only lowers the record.
- A source's reports on one belief are expected to agree with each other;
  a kind whose subject changes over time needs a comparator that allows it.
- The round is the window within which a group counts once. ADR-0007 leaves
  the window open; a round is closed by the caller.
- HMAC-SHA256 is the only integrity scheme written. It is in the standard
  library, but the receiver holds the same secret and could forge a packet.
  Since trust does not rest on it, that limits integrity, not trust. Another
  scheme can be added behind the ``Signer`` and ``Verifier`` interfaces;
  which, if any, is the author's call (AGENTS.md principle 10).
- Unsigned packets are admitted from a node enrolled without a verifier, and
  a node enrolled with one must sign. Whether a receiver should require
  integrity checks for every node is left open.
- Report data that is a list or a mapping travels as a SHA-256 digest, not in
  full, to keep packets small for an edge link. No packet size, latency or
  power figure is claimed or measured.
- A hybrid-agent observation's ``source`` (``deploy_log``, ``metrics``,
  ``diff``, ``compute.compare_windows``) is used as the kind of observation
  that trust is held for.

Usage
-----
``examples/edge_node.py`` runs one worked example end to end, from a recorded
or a live hybrid-agent report.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import ClassVar, Protocol

from episteme.core import EpistemicCore
from episteme.experience import ExperienceLoop, Observation
from episteme.interface import Claim
from episteme.memory import EpistemicMemory
from episteme.models import BeliefType

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


def packet_from_report(
    node_id: str,
    signer: Signer | None,
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
    packet = Packet(node_id, sent_at, items, hypotheses, unknowns)
    # Signing is an integrity check, optional; it never changes a weight.
    return packet if signer is None else sign(packet, signer)


# ----------------------------------------------------------------------
# Trust: each node's own record of each source, from behaviour over time
# and consistency with independent data (the author's ruling, 23 Nov 2026)
# ----------------------------------------------------------------------

#: The id a node uses for its own observations: its own sensors, its own
#: hybrid-agent run. It is never enrolled, never revoked and has no record.
SELF = "self"


@dataclass(frozen=True)
class Policy:
    """The figures a node sets for itself, for its own context (ADR-0007 s. 10).

    There are no defaults (the author, 23 November 2026: *"If the figures are
    arbitrary then they are either fuzzy or should be abstracted out"*). The
    mechanism holds no figure of its own; the node that judges supplies every
    one, never the source judged, and checks here hold only what makes the
    mechanism mean what it says (a discount in (0, 1], ground truth outranking
    consistency, and so on). No figure here is a trust score for any source.
    """

    #: Weight a ground-truth check adds to a record.
    ground_truth_weight: Fraction
    #: Weight a consistency check adds. At most the ground-truth weight, so a
    #: lone source later found right is not out-voted by agreement.
    consistency_weight: Fraction
    #: A failed check weighs this many times a passed one; above 1, trust
    #: falls faster than it rises (ADR-0007 s. 8). It also sets where a
    #: degree of consistency counts as agreement (``agrees``).
    failure_multiple: Fraction
    #: Both counts are multiplied by this at every new outcome, so recent
    #: behaviour counts most and a long good run cannot cushion a switch.
    discount: Fraction
    #: No source's trust exceeds this, however long its record.
    ceiling: Fraction
    #: The reliability of the node's own observations.
    own_reliability: Fraction
    #: Most weight one correlation group may ever add to one belief, both
    #: sides together.
    cap: Fraction
    #: Share of received items drawn for a ground-truth audit, whatever the
    #: source's record: checks never stop (ADR-0007 s. 8).
    audit_rate: Fraction
    #: How many recent deviations from independent references are averaged
    #: to detect slow drift.
    drift_window: int

    def __post_init__(self) -> None:
        for name in ("ground_truth_weight", "consistency_weight", "failure_multiple", "cap"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 < self.discount <= 1:
            raise ValueError("discount must be in (0, 1]")
        if not 0 < self.ceiling < 1:
            raise ValueError("ceiling must be in (0, 1)")
        if not 0 <= self.own_reliability <= 1:
            raise ValueError("own_reliability must be in [0, 1]")
        if self.consistency_weight > self.ground_truth_weight:
            raise ValueError("ground truth must outrank consistency")
        if self.failure_multiple < 1:
            raise ValueError("failure_multiple must be at least 1: trust may not fall slower")
        if not 0 < self.audit_rate <= 1:
            raise ValueError("audit_rate must be in (0, 1]: checks never stop")
        if self.drift_window < 2:
            raise ValueError("drift_window must be at least 2")

    def agrees(self, degree: Fraction) -> bool:
        """Whether a degree of consistency counts as agreement where a yes or no is needed.

        It does when the share it adds to successes outweighs the share it adds
        to failures: ``degree > failure_multiple * (1 - degree)``. No new figure.
        """
        return degree > self.failure_multiple * (1 - degree)


@dataclass(frozen=True)
class RecordEntry:
    """One appended entry: enrolment, a group, a revocation, or an outcome."""

    action: str
    node_id: str
    reason: str
    context: str = ""
    passed: bool | None = None
    alpha: Fraction = Fraction(0)
    beta: Fraction = Fraction(0)
    detail: str = ""


#: A new source's record: the uniform Beta(1, 1), neutral (ADR-0007 s. 3).
NEUTRAL = (Fraction(1), Fraction(1))


class SourceLedger:
    """A node's own, append-only record of every source it hears from.

    Trust is held per (source, context): a source may be semi-trusted in one
    context and less so in another (the author, 23 November 2026), and a record
    earned in one gives nothing in another (ADR-0007 s. 2 and s. 8). A context
    is a kind of observation, optionally narrowed by a ``Route``'s own context.
    Trust in a (source, context) pair is the mean of a discounted Beta record of
    how the source's reports held up: against ground truth, and against data
    from independent sources. It starts neutral and unverified, and an
    unverified pair's reports are leads, admitted at no weight.

    People enrol names, declare correlation groups and revoke; none of those
    sets a figure. There is no method that takes a figure from a person, a
    peer's vouching, a signature, a report count or time online.
    """

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self._entries: list[RecordEntry] = []
        self._enrolled: set[str] = set()
        self._verifiers: dict[str, Verifier] = {}
        self._counts: dict[tuple[str, str], tuple[Fraction, Fraction]] = {}
        self._verified: set[tuple[str, str]] = set()
        self._suspended: set[tuple[str, str]] = set()
        self._groups: dict[str, str] = {}
        self._revoked: set[str] = set()

    @property
    def entries(self) -> tuple[RecordEntry, ...]:
        return tuple(self._entries)

    def _append(self, entry: RecordEntry) -> None:
        if not entry.reason.strip():
            raise ValueError("every record entry needs a reason")
        self._entries.append(entry)

    # --- what people record: names, groups, revocation; never a figure -----

    def enrol(self, node_id: str, verifier: Verifier | None = None, *, reason: str) -> None:
        """Enrol a source's name, optionally with a verifier for integrity only."""
        if node_id == SELF:
            raise ValueError(f"{SELF!r} is the node's own id and cannot be enrolled")
        if node_id in self._enrolled:
            raise ValueError(f"node {node_id!r} is already enrolled")
        if verifier is None:
            detail = "no integrity check"
        else:
            kind = "symmetric" if verifier.symmetric else "asymmetric"
            detail = f"{verifier.scheme} ({kind}) {verifier.fingerprint()}"
        self._append(RecordEntry("enrol", node_id, reason, detail=detail))
        self._enrolled.add(node_id)
        if verifier is not None:
            self._verifiers[node_id] = verifier

    def declare_group(self, group: str, node_ids: Iterable[str], *, reason: str) -> None:
        """Declare sources that share a cause (sensor, firmware, model, site)."""
        for node_id in node_ids:
            self._append(RecordEntry("group", node_id, reason, detail=group))
            self._groups[node_id] = group

    def revoke(self, node_id: str, *, reason: str) -> None:
        self._append(RecordEntry("revoke", node_id, reason))
        self._revoked.add(node_id)

    # --- what the node records: outcomes it checked itself ----------------

    def record_ground_truth(
        self, node_id: str, context: str, *, correct: bool, against: str
    ) -> bool:
        """Record a report checked against ground truth. Returns True if this suspended it.

        A pass verifies the pair. A failure of a verified pair suspends it at
        once: it returns to unverified (ADR-0007 s. 8).
        """
        was_verified = (node_id, context) in self._verified
        self._outcome(node_id, context, self.policy.ground_truth_weight,
                      Fraction(int(correct)), f"ground truth: {against}", passed=correct)
        if correct:
            self._verified.add((node_id, context))
            self._suspended.discard((node_id, context))
            return False
        if was_verified:
            self._suspend(node_id, context, f"failed against {against}")
            return True
        return False

    def record_consistency(
        self, node_id: str, context: str, *, degree: Fraction, reference: str
    ) -> bool:
        """Record how far a report agreed with data from an independent source.

        *degree* runs from 0 (no agreement) to 1 (full): ``degree`` of the
        consistency weight goes to the source's successes and ``1 - degree``
        (times the failure multiple) to its failures. Returns whether the
        degree counts as agreement (``Policy.agrees``).

        The reference must be the node's own observation or a source verified
        for the same context, in a different correlation group; anything else is
        refused, so sources cannot raise one another from nothing and agreement
        inside a group is not evidence. Agreement verifies an unverified pair;
        disagreement lowers the record without suspending (only ground truth
        suspends).
        """
        degree = Fraction(degree)
        if not 0 <= degree <= 1:
            raise ValueError("degree must be in [0, 1]")
        if reference == node_id or self.group(reference) == self.group(node_id):
            raise ValueError(f"{reference!r} is not independent of {node_id!r}")
        if reference != SELF and not self.is_verified(reference, context):
            raise ValueError(f"{reference!r} is not verified for {context!r}")
        agrees = self.policy.agrees(degree)
        self._outcome(node_id, context, self.policy.consistency_weight, degree,
                      f"consistency with {reference}", passed=agrees)
        if agrees and (node_id, context) not in self._suspended:
            # Agreement verifies a new pair; only ground truth lifts a suspension.
            self._verified.add((node_id, context))
        return agrees

    def record_behaviour(self, node_id: str, context: str, *, finding: str, detail: str) -> bool:
        """Record a finding in the source's own behaviour: self-contradiction or drift.

        Either is a failure, and suspends a verified pair at once, as a failed
        ground-truth check does: a source that contradicts itself, or drifts
        away from independent data, is unverified until a check settles which
        of its reports was right. Returns True if this suspended it.
        """
        if finding not in ("self-contradiction", "drift"):
            raise ValueError(f"unknown finding {finding!r}")
        was_verified = (node_id, context) in self._verified
        self._outcome(node_id, context, self.policy.consistency_weight, Fraction(0),
                      f"{finding}: {detail}", passed=False)
        if was_verified:
            self._suspend(node_id, context, f"{finding}: {detail}")
            return True
        return False

    def _suspend(self, node_id: str, context: str, reason: str) -> None:
        self._verified.discard((node_id, context))
        self._suspended.add((node_id, context))
        self._append(RecordEntry("suspend", node_id, reason, context))

    def _outcome(self, node_id: str, context: str, weight: Fraction, degree: Fraction,
                 reason: str, *, passed: bool) -> None:
        """Discount the record, then add *degree* of *weight* as success, the rest as failure."""
        alpha, beta = self._counts.get((node_id, context), NEUTRAL)
        d = self.policy.discount
        alpha = alpha * d + weight * degree
        beta = beta * d + weight * (1 - degree) * self.policy.failure_multiple
        self._append(RecordEntry("check", node_id, reason, context, passed, alpha, beta))
        self._counts[(node_id, context)] = (alpha, beta)

    # --- reading the record ------------------------------------------------

    def is_enrolled(self, node_id: str) -> bool:
        return node_id in self._enrolled

    def is_revoked(self, node_id: str) -> bool:
        return node_id in self._revoked

    def verifier(self, node_id: str) -> Verifier | None:
        return self._verifiers.get(node_id)

    def is_verified(self, node_id: str, context: str) -> bool:
        return (node_id, context) in self._verified

    def trust(self, node_id: str, context: str) -> Fraction:
        """The record's mean, held under the ceiling. Neutral 1/2 for a new pair."""
        alpha, beta = self._counts.get((node_id, context), NEUTRAL)
        return min(self.policy.ceiling, alpha / (alpha + beta))

    def weight(self, node_id: str, context: str) -> Fraction:
        """What a report is admitted at: its trust if verified, else nothing."""
        return self.trust(node_id, context) if self.is_verified(node_id, context) else Fraction(0)

    def group(self, node_id: str) -> str:
        """The source's declared group, or a group of its own."""
        if node_id == SELF:
            return SELF
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
    #: Narrows the trust context below the kind (a site, a time of day, a
    #: load regime). Empty means the kind alone.
    context: str = ""

    def context_of(self, item: Item) -> str:
        return item.kind if not self.context else f"{item.kind}@{self.context}"


@dataclass(frozen=True)
class Offer:
    node_id: str
    group: str
    item: Item
    belief_id: str
    supporting: bool
    weight: Fraction
    #: The context trust was held in for this offer, recorded on the evidence.
    context: str = ""


@dataclass(frozen=True)
class Award:
    offer: Offer
    applied: Fraction
    reason: str


def _offer_key(o: Offer) -> tuple:
    return (o.belief_id, o.group, o.node_id, o.item.item_id, o.supporting)


def aggregate(
    offers: Iterable[Offer], used: dict[tuple[str, str], Fraction], cap: Fraction
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
    """What happened to one item: a lead, absorbed, or offered to the core."""

    node_id: str
    item_id: str
    belief_id: str
    supporting: bool
    offered: Fraction
    applied: Fraction
    revised: bool
    reason: str


@dataclass(frozen=True)
class _Seen:
    node_id: str
    group: str
    item: Item
    belief_id: str
    context: str


@dataclass
class EdgeNode:
    """A node's receiving side: its own store, its own record of sources, its routes.

    *comparators* say, per kind, how far two items about the same belief
    agree: a degree from 0 to 1, or None where they cannot be compared.
    """

    node_id: str
    memory: EpistemicMemory
    ledger: SourceLedger
    routes: list[Route]
    comparators: dict[str, Callable[[Item, Item], Fraction | None]] = field(default_factory=dict)
    #: Per kind: a signed deviation of an item from a reference, and the limit
    #: on its recent mean beyond which a source is drifting.
    deviations: dict[str, tuple[Callable[[Item, Item], Fraction | None], Fraction]] = field(
        default_factory=dict
    )
    #: Secret to this node, so a source cannot tell which items will be audited.
    audit_salt: bytes = field(default_factory=lambda: os.urandom(16), repr=False)
    core: EpistemicCore = field(default_factory=EpistemicCore)
    claims: list[Claim] = field(default_factory=list)
    unknowns: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    received: list[tuple[str, str]] = field(default_factory=list)
    disputes: list[tuple[str, str, str, str]] = field(default_factory=list)
    audits: list[tuple[str, str]] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    _history: dict[tuple[str, str, str], list[Item]] = field(default_factory=dict)
    _drift: dict[tuple[str, str], list[Fraction]] = field(default_factory=dict)
    _pending: list[Offer] = field(default_factory=list)
    _seen: list[_Seen] = field(default_factory=list)
    _contexts: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    _used: dict[tuple[str, str], Fraction] = field(default_factory=dict)
    _evidence_from: dict[str, str] = field(default_factory=dict)

    def receive(self, packet: Packet) -> bool:
        """Check a peer's packet and queue its items for the round.

        Returns False, with the reason in ``refused``, if the packet is
        refused whole: unenrolled, revoked, or failing the integrity check
        enrolled for the node. An admitted packet is recorded in ``received``
        as ``verified`` or ``unchecked``; which one has no effect on any
        weight. Items from a source not yet verified for their kind are leads:
        offered at no weight, and still compared for consistency.
        """
        if packet.node_id == SELF or not self.ledger.is_enrolled(packet.node_id):
            self.refused.append((packet.node_id, "not enrolled"))
            return False
        if self.ledger.is_revoked(packet.node_id):
            self.refused.append((packet.node_id, "revoked"))
            return False
        verifier = self.ledger.verifier(packet.node_id)
        if verifier is None:
            integrity = "unchecked"
        else:
            if packet.scheme != verifier.scheme:
                self.refused.append((
                    packet.node_id,
                    f"integrity: scheme {packet.scheme!r} is not the enrolled {verifier.scheme!r}",
                ))
                return False
            if not verifier.verify(packet.body(), packet.signature):
                self.refused.append((packet.node_id, "integrity: signature does not verify"))
                return False
            integrity = "verified"
        self.received.append((packet.node_id, integrity))

        for item in packet.items:
            if self._audit_drawn(packet.node_id, item.item_id):
                self.audits.append((packet.node_id, item.item_id))
            self._queue(packet.node_id, item, None)
        for text in packet.hypotheses:
            # A hypothesis is a proposal, never a belief (ADR-0006).
            self.claims.append(Claim(text=text, type=BeliefType.THEORY,
                                     source=f"node:{packet.node_id}"))
        for text in packet.unknowns:
            self.unknowns.append((packet.node_id, text))
        return True

    def observe_own(self, report: dict) -> None:
        """Queue the node's own observations (its own hybrid-agent run, its sensors).

        They are evidence at ``own_reliability`` and the reference that
        sources are checked for consistency against.
        """
        own = packet_from_report(SELF, None, report, sent_at="")
        for item in own.items:
            self._queue(SELF, item, self.ledger.policy.own_reliability)

    def _audit_drawn(self, node_id: str, item_id: str) -> bool:
        """Whether this item is drawn for a ground-truth audit, by lot, after arrival.

        A keyed hash, so the draw is reproducible here and unpredictable to the
        source, and independent of the source's record: a long good run buys no
        exemption.
        """
        rate = self.ledger.policy.audit_rate
        h = int.from_bytes(
            hashlib.sha256(self.audit_salt + _canonical([node_id, item_id])).digest(), "big"
        )
        return h * rate.denominator < rate.numerator * 2**256

    def _queue(self, node_id: str, item: Item, own: Fraction | None) -> None:
        """Queue one offer per route the item bears on, weighted in that route's context.

        *own* is the node's own reliability for its own items; a source's
        items are weighted by its record in each context.
        """
        group = self.ledger.group(node_id)
        for route in self.routes:
            if route.kind != item.kind:
                continue
            direction = route.direction(item)
            if direction is None:
                continue
            context = route.context_of(item)
            weight = own if own is not None else self.ledger.weight(node_id, context)
            stated = item.stated_reliability
            # A source may lower its own weight, never raise it (ADR-0007 s. 2).
            if stated is not None:
                weight = min(weight, Fraction(stated))
            self._contexts.setdefault((node_id, item.item_id), set()).add(context)
            self._pending.append(Offer(node_id, group, item, route.belief_id, direction, weight,
                                       context))
            self._seen.append(_Seen(node_id, group, item, route.belief_id, context))

    def _check_consistency(self) -> None:
        """Compare each source's items with independent references, once per group.

        References are the node's own items and items from sources verified
        at the start of the round, in another group. What is learned moves
        the record for later rounds; this round's weights are already set.
        """
        verified = {
            (s.node_id, s.context)
            for s in self._seen
            if s.node_id == SELF or self.ledger.is_verified(s.node_id, s.context)
        }
        seen = sorted(self._seen, key=lambda s: (s.belief_id, s.group, s.node_id, s.item.item_id))
        for s in seen:
            if s.node_id == SELF:
                continue
            compare = self.comparators.get(s.item.kind)
            if compare is None:
                continue
            self._check_against_own_history(s, compare)
            groups_used: set[str] = set()
            for ref in seen:
                if (
                    ref.belief_id != s.belief_id
                    or ref.context != s.context
                    or ref.group == s.group
                    or ref.group in groups_used
                    or (ref.node_id, ref.context) not in verified
                ):
                    continue
                degree = compare(s.item, ref.item)
                if degree is None:
                    continue
                groups_used.add(ref.group)  # an independent group counts once
                agrees = self.ledger.record_consistency(
                    s.node_id, s.context, degree=degree, reference=ref.node_id
                )
                self._track_drift(s, ref)
                if not agrees:
                    # Disagreement is kept, never dropped (AGENTS.md 5).
                    self.disputes.append(
                        (s.node_id, s.item.item_id, ref.node_id, ref.item.item_id)
                    )

    def _check_against_own_history(
        self, s: _Seen, compare: Callable[[Item, Item], Fraction | None]
    ) -> None:
        """A source's new item must agree with what it said before on the same belief.

        GUESS: a belief is about one fixed thing (one deploy's effect), so a
        source's reports on it should agree; a kind whose subject changes over
        time needs a comparator that allows for that.
        """
        key = (s.node_id, s.context, s.belief_id)
        for earlier in self._history.get(key, []):
            if earlier.item_id == s.item.item_id:
                continue
            degree = compare(s.item, earlier)
            if degree is not None and not self.ledger.policy.agrees(degree):
                self.disputes.append((s.node_id, s.item.item_id, s.node_id, earlier.item_id))
                if self.ledger.record_behaviour(
                    s.node_id, s.context, finding="self-contradiction",
                    detail=f"{s.item.item_id} against its own {earlier.item_id}",
                ):
                    self._flag_for_review(s.node_id)
                break
        self._history.setdefault(key, []).append(s.item)

    def _track_drift(self, s: _Seen, ref: _Seen) -> None:
        """Average the source's recent signed deviations from independent references.

        Each report can agree well enough with its reference while all of
        them lean one way; the mean over ``drift_window`` catches that.
        """
        spec = self.deviations.get(s.item.kind)
        if spec is None:
            return
        deviation, limit = spec
        d = deviation(s.item, ref.item)
        if d is None:
            return
        window = self.ledger.policy.drift_window
        recent = self._drift.setdefault((s.node_id, s.context), [])
        recent.append(Fraction(d))
        del recent[:-window]
        if len(recent) == window:
            mean = sum(recent, Fraction(0)) / window
            if abs(mean) > limit:
                recent.clear()  # flagged once; a new window starts
                if self.ledger.record_behaviour(
                    s.node_id, s.context, finding="drift",
                    detail=f"mean deviation {mean} over {window} beyond {limit}",
                ):
                    self._flag_for_review(s.node_id)

    def _flag_for_review(self, node_id: str) -> None:
        for belief_id in self.resting_on(node_id):
            if belief_id not in self.review:
                self.review.append(belief_id)

    def close_round(self) -> list[Outcome]:
        """Check consistency, aggregate the round's offers and apply the awards."""
        self._check_consistency()
        self._seen = []
        awards, _ = aggregate(self._pending, self._used, self.ledger.policy.cap)
        self._pending = []
        loop = ExperienceLoop(self.core, self.memory)
        outcomes: list[Outcome] = []
        for award in awards:
            o = award.offer
            if award.applied == 0:
                reason = award.reason if o.weight else "lead: source not verified in this context"
                outcomes.append(Outcome(o.node_id, o.item.item_id, o.belief_id, o.supporting,
                                        o.weight, award.applied, False, reason))
                continue
            observation = Observation(
                content=f"{o.item.kind}: {o.item.summary} [{o.item.item_id}]",
                source=f"node:{o.node_id}",
                reliability=float(award.applied),
                node=o.node_id,
                kind=o.context,
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

    def check_ground_truth(
        self, node_id: str, item_id: str, *, correct: bool, against: str,
        context: str | None = None,
    ) -> list[str]:
        """Record a ground-truth check of one received item.

        The outcome is recorded in *context*, or in every context the item
        was routed into when none is named; other contexts are untouched.
        Returns the beliefs to review if the check suspended the source:
        those holding its evidence. None is recomputed (AGENTS.md 3).
        """
        contexts = self._contexts.get((node_id, item_id))
        if contexts is None:
            raise ValueError(f"no item {item_id!r} received from {node_id!r}")
        if context is not None:
            if context not in contexts:
                raise ValueError(f"item {item_id!r} was not routed into {context!r}")
            contexts = {context}
        suspended = False
        for c in sorted(contexts):
            suspended |= self.ledger.record_ground_truth(
                node_id, c, correct=correct, against=against
            )
        if not suspended:
            return []
        self._flag_for_review(node_id)
        return self.resting_on(node_id)

    def resting_on(self, node_id: str) -> list[str]:
        """Belief ids holding evidence from *node_id*, for a person to review."""
        ids = {e for e, n in self._evidence_from.items() if n == node_id}
        return sorted(
            b.id
            for b in self.memory.list_beliefs()
            if b.id is not None and ids & {*b.evidence_ids, *b.counter_evidence_ids}
        )


# ----------------------------------------------------------------------
# A route and comparators for hybrid-agent's before/after comparison
# ----------------------------------------------------------------------


def p95_rose(item: Item) -> bool | None:
    """Route rule: a before/after comparison supports a p95 regression if p95 rose."""
    change = item.data.get("p95_change_pct")
    if not isinstance(change, (int, float)):
        return None
    return change > 0


def _p95(a: Item, b: Item) -> tuple[Fraction, Fraction] | None:
    x, y = a.data.get("p95_change_pct"), b.data.get("p95_change_pct")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return Fraction(str(x)), Fraction(str(y))


@dataclass(frozen=True)
class P95Check:
    """How a node compares two p95 comparisons. Both figures are the node's own.

    *spread_pp*: how many percentage points apart two changes in the same
    direction must be for their degree of consistency to reach 0.
    *drift_limit_pp*: a mean lean beyond this over the drift window is drift,
    though each report may agree well enough on its own. No default for either.
    """

    spread_pp: Fraction
    drift_limit_pp: Fraction

    def __post_init__(self) -> None:
        if self.spread_pp <= 0 or self.drift_limit_pp <= 0:
            raise ValueError("spread_pp and drift_limit_pp must be positive")

    def degree(self, a: Item, b: Item) -> Fraction | None:
        """0 if p95 moved opposite ways; else 1 at equal changes, falling to 0 at the spread.

        GUESS: the straight-line fall. Any shape that is 1 for identical
        reports and falls as they part would serve.
        """
        pair = _p95(a, b)
        if pair is None:
            return None
        x, y = pair
        if (x > 0) != (y > 0):
            return Fraction(0)
        return max(Fraction(0), 1 - abs(x - y) / self.spread_pp)

    def deviation(self, a: Item, b: Item) -> Fraction | None:
        """Signed deviation: how far *a*'s p95 change sits above *b*'s."""
        pair = _p95(a, b)
        return None if pair is None else pair[0] - pair[1]
