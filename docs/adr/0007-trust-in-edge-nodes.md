# ADR-0007: Trust in an edge node rests on its behaviour over time and its consistency with other data

- **Status:** Accepted (the author, 23 November 2026)
- **Date:** 2026-11-22
- **Depends on:** ADR-0006 (Accepted the same day).

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

## Decision

### 1. Identity is not trust, and trust does not rest on signatures

The author's ruling, 23 November 2026: *"Trust is not based on cryptographic
signatures - key management is a weak link."*

A person enrols a node by recording its name, who enrolled it and when.
Enrolment gives no trust (section 3). A report from a node nobody enrolled, or
from a revoked node, is refused.

A signature is an optional integrity check, not a ground for trust. A person
may enrol a verifier for a node (a public key, or another scheme); that node's
reports must then pass it, and one that fails is refused as damaged or
tampered. A node enrolled without one is admitted unsigned. Whether a report
was signed never changes the weight it is admitted at.

A node's name in a report is therefore a claim, not a proof: without a
verifier anyone who reaches the receiver can claim it, and with one a stolen
or mismanaged key does the same. Neither case is assumed away. What bounds the
damage is what does not rest on keys: trust only as the source's own
behaviour earned it on the receiving node's checks (sections 3, 4 and 8), the per-record cap of
ADR-0005, correlation groups (section 5), and a cap on what one group may add
to any one belief. That bound is THEORY, not a measured resistance to any
attack.

### 2. Trust is per node and per context, never one score

The author, 23 November 2026: *"Neither is peer trust reliable"*, and *"They
might be semi-trusted in one context but less so in another."*

Trust is held by each receiving node, in its own record, for a pair: a source
and a context. A context is a kind of observation (a temperature reading, an
image classification, a summary of a log), narrowed where the receiving node
declares it to a site, a time of day, a load regime or the like. A source
trusted in one context has no trust in another until its behaviour there earns
it, and a failure in one leaves the others as they were. No person sets a
figure in the record, and no peer's figure or vouching enters it. The
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
- A pair becomes verified when its first checked outcome (section 4) is
  recorded and is found right.

Every outcome is appended, with what it was checked against, to a record
that is never overwritten (the ADR-0002 discipline applied to trust).

### 4. Trust rests on behaviour over time and consistency with other data

The author's ruling, 23 November 2026: trust rests on *"behaviour over time
and consistency with other data sources."*

Trust in a pair is the mean of a Beta posterior over checked outcomes, by the
arithmetic of ADR-0005 with the changes section 8 needs: a pass adds to α, a
failure to β, starting from the neutral prior; older outcomes count for less
than recent ones; and a failure counts for more than a pass. Two kinds of
check count:

- **Ground truth:** a person's inspection, a reference instrument, or a ground
  truth recorded later. It weighs more than consistency, so a lone source that
  turns out right is not out-voted.
- **Consistency with other data sources:** the report compared with the
  receiving node's own observations, or with a source verified in the same
  context and in a different correlation group. Each independent group counts
  once. A source cannot be raised by sources that nobody has checked, so
  agreement among unverified peers verifies nothing. A mismatch is kept as a
  dispute, never dropped.
- **Consistency is a degree.** A comparison returns how far two reports
  agree, from 0 to 1, not a pass or a fail at a tolerance's edge (the
  author's direction, 23 November 2026, that an arbitrary figure be fuzzy or
  abstracted out). A check of degree *d* adds *d* of its weight to α and
  *1 - d* to β, so a near miss costs a little and a wide one a lot. Where a
  yes or no is still needed (whether a check verifies a new pair, whether it
  is a dispute or a self-contradiction), a degree counts as agreement when
  what it adds to α outweighs what it adds to β, so the cut follows from how
  heavily the node weighs a failure and adds no figure of its own. How the
  degree is drawn from the data is each node's, per kind.

Each check is appended with what was checked against what.

Trust is never revised by:

- agreement with other nodes as such, or one node vouching for another
  (consensus is not evidence; ADR-0006);
- a figure a person or a peer sets;
- the number of reports a node sends (volume is not a truth signal, AGENTS.md 8);
- time online without checks;
- the node's own statement of its accuracy.

Without checked outcomes, trust stays where it is: it does not rise, and an
unverified pair stays unverified. A person may revoke a node (section 7) but
sets no figure.

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
report falsely once its trust is high. The author, 23 November 2026: *"A
covert node or agent may pretend to be good then shift its behaviour in subtle
ways, behaving in malicious ways or even accidently contradicting itself."*
The design assumes any node may do this, maliciously or by accident, and
limits what a good history is worth:

- **Checks never stop.** Outcomes are checked for the life of a node, not only
  while it is new. Which reports are checked is drawn by lot, at a stated
  rate, after the report has arrived, so a node cannot tell which of its
  reports will be checked and cannot behave well only on those. Consistency
  with other data (section 4) is checked on every report, whatever the record.
- **Self-contradiction is a failure.** A report on a belief is compared with
  what the same node said before on that belief, in the same context. A
  contradiction is kept as a dispute and counts as a failure.
- **Slow drift is a failure.** A subtle shift can keep every report agreeing
  well enough with each comparison while all of them lean one way. The receiving
  node averages a node's signed deviations from independent data over a
  stated window of reports; a mean beyond a stated limit is drift, and counts
  as a failure.
- **Recent outcomes count most.** Each pair's α and β are discounted by a
  stated factor at every new checked outcome, so a long good history cannot
  cushion a switch: after a switch, trust falls within a few failed checks
  rather than over as many as it took to build.
- **Failure counts more than success.** A failed check adds a stated multiple
  of the weight a passed check adds. Trust is slow to earn and quick to lose.
- **A failure after a good run suspends.** When a verified pair fails a
  ground-truth check, contradicts itself or drifts, it returns to unverified
  (section 3) at once: its reports are recorded and not admitted until a
  ground-truth check, such as a person's review, passes it again; agreement
  with other data alone does not lift a suspension. A single mismatch with
  another source lowers the record without suspending. Every belief its admitted evidence
  supported is listed for that review, most recent first, as in revocation
  (section 7), and none is recomputed silently. The switch may have begun
  before the check that caught it, so the list does not stop at the last
  passed check.
- **Trust has a ceiling below 1.** No pair's trust, however long its record,
  exceeds a stated ceiling, so no single node becomes a source the swarm
  cannot outweigh. Together with the ADR-0005 cap on one record, this bounds
  what one switched node can do before its next check.
- **Good history does not transfer.** A record earned in one context gives
  no trust in another (section 2), so a node cannot build
  trust on easy, checkable readings and spend it on hard, unchecked ones.

### 9. The admission check stays small

Admitting a report needs a lookup of the pair's trust and the node's group,
and an integrity check where one is enrolled: no model, no network call, and
no state beyond the enrolment, trust and group tables. That it fits a small device's budget is
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

The author, 23 November 2026: *"If the figures are arbitrary then they are
either fuzzy or should be abstracted out."* So no figure is built into the
mechanism, not even as a default: each is a parameter the node supplies. And
where a crisp figure would put a cliff in the record, a fuzzy one replaces
it: consistency is a degree (section 4), not a tolerance.

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
  weighs at least as much as a success; ground truth weighs at least as
  much as consistency; the ceiling is below 1; agreement among sources that
  nobody has checked never raises trust (section 4); and trust never
  transfers between contexts (section 2). A context that seems to call for breaking one is recorded as
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
  the ADR-0005 cap and correlation groups limit what one stolen key or
  claimed name can do;
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

- Accepted on 23 November 2026 with ADR-0006, after the prototype merged
  (#47, #48), and built the same day as `episteme/edge.py`. Giving `Evidence`
  a source (node and kind), which would break its id payload, is a separate
  change; until then the source travels in the evidence's own source string.
- Its guards are in `tests/test_edge.py`, one for each:
  - trust in a pair cannot be raised by reports from other nodes agreeing with
    it, however many: `test_agreement_among_unverified_peers_verifies_nothing`;
  - a report from an unverified pair cannot move a belief, although its
    trust is the neutral 0.5 that the core's threshold would admit:
    `test_a_new_source_is_neutral_and_unverified_and_sends_only_leads`;
  - a verified pair that fails one check is unverified at once, however long
    its good record:
    `test_a_verified_source_checked_wrong_is_suspended_and_nothing_recomputed`;
  - no record of passed checks lifts a pair's trust above the ceiling:
    `test_recent_behaviour_counts_most_and_trust_has_a_ceiling`;
  - a node cannot raise the reliability its own report is admitted at:
    `test_a_source_can_lower_its_own_weight_but_never_raise_it`;
  - revoking a node changes no stored belief:
    `test_revocation_changes_no_belief_and_lists_those_resting_on_the_node`;
  - no figure a node sets for its context can breach a floor of section 10:
    `test_policy_refuses_settings_that_change_what_the_mechanism_means`;
  - no node's figures change the trust another node holds in it:
    `test_no_figure_a_source_sends_changes_the_trust_held_in_it`.
- Settled by the author, 22 November 2026: a new node starts neutral and
  unverified (section 3); the design assumes a node may switch (section 8);
  and the remaining figures are set by each node for its own context, within
  fixed floors (section 10).
- Left open: nothing in this record. How a node turns its context into
  figures is a design for the build, decided with it, and does not change
  the floors.
