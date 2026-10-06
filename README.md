# swarm

EPISTEME is an epistemic foundation model architecture for representing beliefs,
evaluating evidence, and maintaining auditable revision history.

## Purpose

This repository provides a compact Python implementation of an epistemic system
where:

- beliefs are explicit typed objects with confidence and lifecycle state,
- evidence is validated before it can influence beliefs,
- update rules are enforced by a side-effect-free core,
- revisions are persisted with immutable history for auditability.

## Repository layout

- `episteme/models.py` – core data models
- `episteme/core.py` – epistemic rule engine
- `episteme/memory.py` – SQLite-backed memory layer
- `episteme/interface.py` – language/LLM adapter
- `episteme/experience.py` – observation-to-revision loop
- `episteme/population.py` – population synthesis: cited structure over many holders' positions
- `examples/archipelago_first_fork.py` – the synthesis run over a published Archipelago export
- `tests/` – unit tests for all modules
- `docs/adr/` – architectural decision records

## Population synthesis

`episteme/population.py` applies the same discipline to a population that the
rest of the package applies to one agent. Given holders with declared values
and their recorded utterances (a vote, a petition, a stated goal), each with a
citation to the record it came from, `synthesise` returns structure: clusters
of holders by value (deterministic farthest-first, no randomness), each
position with who holds it, its support per cluster, how many changed their
mind to reach it and every citation behind it, and the positions that bridge
every cluster that spoke. `agreement` compares two clusterings by the Rand
index, so a structure that survives a change of method can be told from an
artefact of one. `claims` turns positions into `Claim` proposals of type
OPINION whose confidence is a share, not a verdict; the module can produce no
`Belief`. It generates no interpretation: a `Synthesis` carries an
`Interpretation` only when a named author supplies one (ADR-0004).

The design it serves is a chamber whose candidates are drawn by lot and
elected as normal (`dermot-r-cochran/Voting`, `docs/lot-then-vote.md`), where
the synthesis is a briefing to the drawn, who may dissent from it on the
record. The first population it reads is The Archipelago's simulated citizens
(`examples/archipelago_first_fork.py`, from a checkout of
`dermot-r-cochran/virtual-anthropology`), who have no privacy to lose and a
hash-chained record to check the synthesis against.

## Architectural overview

The system is organized as five collaborating layers:

1. **Models** define belief, evidence, and revision primitives.
2. **Core** applies deterministic eligibility and state-transition rules.
3. **Memory** persists current belief state plus full revision history.
4. **Language Interface** allows claim extraction/formatting but does not write beliefs.
5. **Experience Loop** transforms observations into evidence and requests revisions.

### High-level flow

1. A claim or observation is produced.
2. Evidence is generated (or deduplicated) from that input.
3. `EpistemicCore` validates whether an update is eligible.
4. `EpistemicMemory` applies the update and appends a revision record.
5. Consumers query current beliefs and/or revision history.

## Getting started

### Requirements

- Python 3.11+

### Install

```bash
cd <repository-root>
python -m pip install -e ".[dev]"
```

## Development workflow

Run tests:

```bash
cd <repository-root>
python -m pytest
```

Run lint checks:

```bash
cd <repository-root>
ruff check .
```

## Architectural decision records (ADRs)

Design decisions are tracked in markdown under:

- `docs/adr/README.md`
