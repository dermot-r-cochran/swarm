# ADR-0006: A peer network, if one is built, has hybrid-agents as its nodes

- **Status:** Proposed
- **Date:** 2026-11-11

## Context

`dermot-r-cochran/hybrid-agent` is a small engineering agent: a deterministic
controller, an LLM only for semantic steps, and a report that keeps
observations, derived results, hypotheses, unknowns and proposed actions
apart, ending `awaiting_human_review`. Its direction ruling of 11 November
2026 (*A local partner, recipes and workflows*, in its `docs/decisions.md`)
gives it one local partner and no peers. It runs as a command-line tool on
the user's machine and opens no listener, and its hand-over to the partner
never leaves that machine.

The same day the author placed anything wider here: *"peer-to-peer would
require the swarm repo using hybrid-agents as peer nodes"*. A network of
agents exchanging what they found is a belief store spread over several
holders. The failures EPISTEME refuses are the ones such a network invites:
agreement between peers read as evidence, a fluent report promoted to a
belief, and a revision nobody can trace back to what caused it.

Nothing needs a network yet. This record says where one would be built and
under which rules, so that neither repository grows one by accident.

## Decision (proposed)

If a peer network is built, it is built in this repository, and each node is
a hybrid-agent.

- **What a node contributes is its report, read through the existing rules.**
  A node's observations and derived results arrive as evidence with the node
  as their source and a reliability set by people, not by the node. Its
  hypotheses arrive as claims, which are proposals, never beliefs. Its
  unknowns stay unknowns. Its proposed actions are not evidence of anything.
- **Peers agreeing is not evidence.** The core already refuses language,
  repetition and consensus alone as grounds to update a belief. Two nodes
  repeating a third's finding add nothing, and a revision cites the record
  that caused it.
- **Every write keeps its existing path.** Beliefs change only through core
  and then memory (ADR-0001, ADR-0003), every revision is appended
  (ADR-0002), and confidence is the Beta mean of the weighted evidence
  (ADR-0005). No node writes to another's memory, and no node's memory is
  shared.
- **The network is this repository's; the node stays as it is.** Whatever
  carries reports between machines lives here. A hybrid-agent still runs as
  a local command-line tool and opens no listener of its own. A node here
  would run it locally and carry its report, rather than turn it into a
  service.

## Consequences

- Nothing is built. `episteme` gains no dependency on hybrid-agent, and
  hybrid-agent gains no peer code, until a concrete need is shown and this
  record is accepted.
- On acceptance, this record gets its guard test in the same change, as the
  five accepted ADRs did. The likely guard: a node's hypothesis can never be
  stored as a belief, and an update supported only by matching reports from
  other nodes is refused.
- Left open for acceptance: the transport, whether nodes span machines, how
  a node's reliability is set and revised, and whether a node may also take
  evidence from its own local partner.
