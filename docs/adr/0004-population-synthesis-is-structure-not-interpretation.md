# ADR-0004: Population synthesis is cited structure, never interpretation

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

A synthesis of what many people have said (citizens' opinions, values and
needs, gathered for a deliberative body) is a belief store about a
population. Language models make such syntheses cheap, and the known failure
modes are the ones EPISTEME exists to refuse: a fluent summary that reads as
more agreed than the data were, minority positions sanded off to reach a
consensus statement, a frame chosen by whoever prompted the model, and a
"meaning" nobody signed. The design this module serves (`dermot-r-cochran/Voting`,
`docs/lot-then-vote.md`) wants the synthesis as a briefing to a drawn
chamber, whose members may dissent from it on the record.

## Decision

`episteme/population.py` emits **structure with citations and nothing else**:

- clusters of holders by their declared values, by a deterministic method;
- each position with the holders who take it, its support per cluster, how
  many holders changed their mind to reach it, and a citation for every
  utterance behind it;
- the positions that bridge every cluster that spoke on their topic.

It produces `Claim` proposals of type OPINION whose confidence is a share
of the population, never a `Belief`: the module imports neither
`episteme.core` nor `episteme.memory` (ADR-0003's boundary, applied again).
It generates no interpretation: a `Synthesis` carries an `Interpretation`
only when a caller supplies one with a named author, and no function in the
module returns one.

## Consequences

- A reader can check every line of a synthesis against the record it cites.
- Disagreement is preserved as structure (clusters, bridges, a position held
  by one) rather than resolved into a paragraph (AGENTS.md principles 5 and 8).
- Two clusterings can be compared by the Rand index, so a structure that
  survives a change of method is distinguishable from an artefact of one.
- Saying what the structure means is a human's signed act, outside the
  module, which is the same rule The Archipelago's publication pipeline
  enforces with its *interpretation* placeholder.
- Guards: `tests/test_population.py::TestInterpretationNeverGenerated` (no
  function returns an `Interpretation`; an unsigned one is refused) and
  `tests/test_population.py::TestWriteIsolation` (no import path to belief
  storage).
