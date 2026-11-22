# ADR-0007: Trust in an edge node is set by people and revised only by checked outcomes

- **Status:** Proposed
- **Date:** 2026-11-22
- **Depends on:** ADR-0006 (Proposed). If ADR-0006 is not accepted, this record
  lapses with it.

## Context

ADR-0006 places any peer network in this repository, with hybrid-agents as its
nodes, and leaves open "how a node's reliability is set and revised". This
record proposes an answer for the case the author's research direction points
at (22 November 2026): nodes that run at the edge, on small devices with local
sensors, tight compute, memory and power budgets, and intermittent links.

The following are FACT about the code as it stands:

- `Evidence` carries a `reliability` in [0, 1], a `context_hash` and a
  `timestamp`. It carries no source: nothing records which node, sensor or
  person an observation came from.
- `EpistemicCore` refuses evidence below `reliability_threshold` (default 0.5)
  and caps what one record can move a belief by (`max_confidence_delta`,
  ADR-0005).
- Under ADR-0005 reliability is the weight a record adds to α or β. Whoever
  sets reliability therefore sets how far a record can move a belief.
- ADR-0005 records as a known limit that two records sharing an unseen common
  cause count as two.

At the edge those facts meet conditions a single local store does not face:

- **A device can be held by someone else.** Its key can be copied and its
  software changed. A node's report about itself is not evidence about itself.
- **Nodes share causes.** Ten nodes with the same sensor model, the same
  firmware or the same on-device model are not ten independent witnesses. A
  swarm makes the ADR-0005 limit the common case rather than the rare one.
- **Links come and go.** Reports arrive late, in batches and out of order, and
  a device's clock may be wrong.
- **The trust check runs on the device.** Whatever decides whether to admit a
  report must fit the same budget as the node's own work.

The failure to avoid is the one AGENTS.md principles 3, 5 and 8 name: trust
that grows from agreement, volume or a node's own fluency, so that a group of
nodes repeating each other ends up believed.

## Decision (proposed)

### 1. Identity is not trust

Each node has a signing key created on the device. A person enrols the node by
recording its public key, who enrolled it and when. A report that is unsigned,
or signed by a key not enrolled, is refused, not down-weighted. A verified
signature says which node sent a report; it says nothing about whether the
report is right.

### 2. Trust is per node and per kind of observation

Trust is held for a pair: a node and a kind of observation (for example, a
temperature reading, an image classification, a summary of a log). A node
trusted for one kind has no trust for another until a person sets it. The
reliability a record is admitted at is the trust held for its pair. A node may
state a lower reliability for its own reading, and the lower figure is used; it
can never state a higher one.

### 3. A new node is neutral and unverified

The author's ruling, 22 November 2026: *"A new node is neutral and unverified,
keeping in mind that a covert node may pretend to be good and then switch
tactics later on."* Section 8 takes up the second half.

- **Neutral:** a new pair's trust starts at the uniform Beta(1, 1), mean 0.5,
  the same prior ADR-0005 gives a belief stated at 0.5. Enrolment says nothing
  for or against the node.
- **Unverified:** a pair with no checked outcome is unverified, and an
  unverified pair's reports are recorded but not admitted as evidence. They
  move no belief. The gate is the verification state, not the number:
  `EpistemicCore` admits reliability *at or above* its threshold (default
  0.5), so a neutral figure alone would let an unchecked node move beliefs.
- A pair becomes verified when its first checked outcome is recorded and is
  found right. A person may also verify it directly, with a written reason.

Every setting is appended, with who made it and why, to a trust record that
is never overwritten (the ADR-0002 discipline applied to trust).

### 4. Trust is revised only by checked outcomes or by a person

Trust in a pair is the mean of a Beta posterior over checked outcomes, by the
arithmetic of ADR-0005 with the two changes section 8 needs: a report later
found right by an independent check adds to α, one found wrong adds to β,
starting from the neutral prior; older outcomes count for less than recent
ones; and a failure counts for more than a success.
An independent check is one that does not come from the swarm: a person's
inspection, a reference instrument, or a ground truth recorded later. Each
check is appended with what was checked against what.

Trust is never revised by:

- agreement with other nodes (consensus is not evidence; ADR-0006);
- the number of reports a node sends (volume is not a truth signal, AGENTS.md 8);
- time online without checks;
- the node's own statement of its accuracy.

Without checked outcomes, trust stays where it is: it does not rise, and an
unverified pair stays unverified. A person may lower or raise it at any time,
with a reason, as an appended entry.

### 5. Correlated nodes count once

A person may declare a correlation group: nodes sharing a sensor model,
firmware, on-device model, site or upstream data. Within one group, reports
bearing on the same belief inside one window are admitted as one record, at
the highest trust among them. This is the `context_hash` deduplication of the
experience loop raised from one record to one group. A correlation nobody has
declared still counts twice; that part of the ADR-0005 limit stays open, and
is stated rather than solved.

### 6. Late and offline reports

A report is ordered by when it was received, and keeps the node's own
timestamp as a stated value, never as the ordering key. A report from a node
that was offline is admitted on arrival by the same rules as any other; being
late neither raises nor lowers it.

### 7. Revocation keeps the record

A person can revoke a node (a lost or tampered device). Revocation refuses its
later reports and marks its earlier evidence; nothing is deleted (ADR-0002).
Beliefs that rest on the revoked node's evidence are listed for a person's
review. They are not recomputed silently (AGENTS.md 3); a person decides
whether to record counter-evidence or leave them.

### 8. A good record buys no licence: the covert node that switches

A covert node can behave well while it is watched, build a record, and then
report falsely once its trust is high. The design assumes any node may do
this, and limits what a good history is worth:

- **Checks never stop.** Outcomes are checked for the life of a node, not only
  while it is new. Which reports are checked is drawn by lot, at a stated
  rate, after the report has arrived, so a node cannot tell which of its
  reports will be checked and cannot behave well only on those.
- **Recent outcomes count most.** Each pair's α and β are discounted by a
  stated factor at every new checked outcome, so a long good history cannot
  cushion a switch: after a switch, trust falls within a few failed checks
  rather than over as many as it took to build.
- **Failure counts more than success.** A failed check adds a stated multiple
  of the weight a passed check adds. Trust is slow to earn and quick to lose.
- **A failure after a good run suspends.** When a verified pair fails a check,
  it returns to unverified (section 3) at once: its reports are recorded and
  not admitted until a person reviews it. Every belief its admitted evidence
  supported is listed for that review, most recent first, as in revocation
  (section 7), and none is recomputed silently. The switch may have begun
  before the check that caught it, so the list does not stop at the last
  passed check.
- **Trust has a ceiling below 1.** No pair's trust, however long its record,
  exceeds a stated ceiling, so no single node becomes a source the swarm
  cannot outweigh. Together with the ADR-0005 cap on one record, this bounds
  what one switched node can do before its next check.
- **Good history does not transfer.** A record earned on one kind of
  observation gives no trust on another (section 2), so a node cannot build
  trust on easy, checkable readings and spend it on hard, unchecked ones.

### 9. The admission check stays small

Admitting a report needs a signature check and a table lookup for the pair's
trust and the node's group: no model, no network call, and no state beyond
the enrolment, trust and group tables. That it fits a small device's budget is
THEORY until measured on a stated machine; no measurement exists yet.

### 10. The figures are set by each node, for its own context

The author's ruling, 22 November 2026: *"The other questions would depend on
the context as understood by each node."* So the check rate, the discount
factor, the weight of a failure against a success, the ceiling, the
correlation window, and whether a person's direct observation is enrolled as
a source are not constants of the network. Each node sets them for itself,
from its own understanding of its context: what it senses, what a wrong
belief would cost it, how often it can afford a check, how often its links
drop.

- **The node that judges sets them, never the node judged.** Each node keeps
  its own memory (ADR-0006), so each node holds its own trust in its peers and
  applies its own figures to the reports it receives. No node's figures
  decide how far it is itself trusted by another; that would let a node raise
  its own trust, which section 2 forbids.
- **A node's understanding of its context is its own belief.** It is held
  and revised by the existing rules (ADR-0001 to ADR-0005), and every change
  to a figure is appended with the context it was set for and who or what set
  it. A figure changed because of a peer's report is changed only through
  that report's admission as evidence, never directly.
- **Context sets the figures; it cannot remove the floors.** Whatever a node
  understands, these hold everywhere and are the guards: an unverified pair
  is never admitted (section 3); the check rate is above zero; a failure
  weighs at least as much as a success; the ceiling is below 1; agreement
  never raises trust (section 4); and trust never transfers between kinds
  (section 2). A context that seems to call for breaking one is recorded as
  a reason to revisit this record, not acted on.
- **Two nodes may trust the same peer differently.** That is expected, not a
  fault: their contexts differ. Their disagreement is kept (AGENTS.md 5), and
  neither node's trust is evidence for the other.

## How this meets AGENTS.md

- **Principle 3 (no silent updates):** every change to trust is an appended,
  attributed entry; revocation lists affected beliefs instead of changing them.
- **Principle 5 (no drift by exposure):** trust rises only with independent
  checks, never with time or traffic, and a long record cannot lock it in.
- **Principle 8 (volume is not truth):** repetition within a node is already
  deduplicated by `context_hash`; repetition across declared correlated nodes
  is deduplicated by group; agreement never raises trust.
- **Principle 10 (vendor neutrality):** no device, runtime, transport or
  signature scheme is named; the record states the properties a choice must
  have.

## What this does not claim

- **Calibration.** A trust of 0.8 is a summary of checked outcomes, not a
  measured probability that the next report is right. The repository holds no
  outcome data.
- **Resistance to a coordinated attack.** Enrolment by people, per-kind trust,
  the ADR-0005 cap and correlation groups limit what one stolen key can do;
  they do not make the network tolerant of any given share of hostile nodes.
  No such property is claimed or tested.
- **Catching every switch.** Checks drawn by lot make a switch likely to be
  caught, not certain to be. A node that lies rarely, or only on reports that
  are hard to check, may go unnoticed for longer than the check rate
  suggests; how long is unmeasured.
- **Undeclared correlation.** Two nodes with a common cause nobody declared
  still count as two.
- **Budget.** No figure for memory, latency or power is claimed.

## Consequences

- Nothing is built while ADR-0006 is Proposed. On acceptance of both, `Evidence`
  gains a source (node and kind), which is a breaking change to its id payload
  and is decided then, not here.
- On acceptance, this record gets its guard tests in the same change. The
  likely guards:
  - trust in a pair cannot be raised by reports from other nodes agreeing with
    it, however many;
  - a report from an unverified pair cannot move a belief, although its
    trust is the neutral 0.5 that the core's threshold would admit;
  - a verified pair that fails one check is unverified at once, however long
    its good record;
  - no record of passed checks lifts a pair's trust above the ceiling;
  - a node cannot raise the reliability its own report is admitted at;
  - revoking a node changes no stored belief;
  - no figure a node sets for its context can breach a floor of section 10;
  - no node's figures change the trust another node holds in it.
- Settled by the author, 22 November 2026: a new node starts neutral and
  unverified (section 3); the design assumes a node may switch (section 8);
  and the remaining figures are set by each node for its own context, within
  fixed floors (section 10).
- Left open: nothing in this record. How a node turns its context into
  figures is a design for the build, decided with it, and does not change
  the floors.
