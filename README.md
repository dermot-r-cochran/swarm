# swarm

EPISTEME is an epistemic foundation model architecture for representing beliefs,
evaluating evidence, and maintaining auditable revision history.

## Purpose

This repository provides a compact Python implementation of an epistemic system
where:

- beliefs are explicit typed objects with confidence and lifecycle state
  (`tests/test_models.py::TestBelief::test_valid_belief_creation`,
  `tests/test_core.py::TestBeliefStateResolution::test_both_yields_disputed`),
- evidence is validated before it can influence beliefs
  (`tests/test_core.py::TestUpdateEligibility::test_ineligible_low_reliability`,
  `tests/test_experience.py::TestExperienceLoopBasic::test_low_reliability_does_not_revise`),
- update rules are enforced by a side-effect-free core (the rules:
  `tests/test_core.py::TestUpdateEligibility::test_language_only_update_rejected`
  and `::test_confidence_delta_clamped`; that the core writes nothing has no
  test yet: ADR-0001 has no named guard, as `CLAUDE.md` records),
- revisions are persisted with immutable history for auditability
  (`tests/test_memory.py::TestBeliefRevision::test_beliefs_never_deleted`,
  ADR-0002's guard, and `::test_revision_previous_state_preserved`; that a
  stored revision cannot be altered has no test yet).

## Repository layout

- `episteme/models.py` – core data models (tested in `tests/test_models.py`)
- `episteme/core.py` – epistemic rule engine (`tests/test_core.py`)
- `episteme/memory.py` – SQLite-backed memory layer (`tests/test_memory.py`)
- `episteme/interface.py` – language/LLM adapter (`tests/test_interface.py`)
- `episteme/experience.py` – observation-to-revision loop (`tests/test_experience.py`)
- `episteme/population.py` – population synthesis: cited structure over many holders' positions
  (`tests/test_population.py`)
- `examples/archipelago_first_fork.py` – the synthesis run over a published Archipelago export
  (`tests/test_example_archipelago.py::test_example_reads_an_export_and_cites_the_record`)
- `tests/` – unit tests for all modules (`.github/scripts/check_docs.py` fails CI if a module
  in `episteme/` has no `tests/test_<module>.py`)
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
Tested in `tests/test_population.py`: determinism by
`TestClustering::test_deterministic_and_order_independent`, support per cluster by
`TestSynthesis::test_support_is_reported_per_cluster`, changed minds by
`TestSynthesis::test_latest_stance_stands_and_change_is_counted`, bridges by
`TestSynthesis::test_bridge_is_shared_by_every_speaking_cluster`, the Rand index by
`TestAgreement::test_partial_disagreement_is_fractional`, OPINION claims by
`TestClaims::test_claims_are_opinions_with_share_and_citations`, and no generated
interpretation by `TestInterpretationNeverGenerated::test_module_defines_no_interpretation_producer`
and `::test_interpretation_must_be_signed`.

The design it serves is a chamber whose candidates are drawn by lot and
elected as normal (`dermot-r-cochran/Voting`, `docs/lot-then-vote.md`), where
the synthesis is a briefing to the drawn, who may dissent from it on the
record. The first population it reads is The Archipelago's simulated citizens
(`examples/archipelago_first_fork.py`, from a checkout of
`dermot-r-cochran/virtual-anthropology`), who have no privacy to lose and a
hash-chained record to check the synthesis against.

## Architectural overview

The system is organized as five collaborating layers:

1. **Models** define belief, evidence, and revision primitives
   (`tests/test_models.py::TestEvidence`, `::TestBelief`, `::TestBeliefRevision`).
2. **Core** applies deterministic eligibility and state-transition rules
   (`tests/test_core.py::TestUpdateEligibility::test_eligible_update`,
   `::TestBeliefStateResolution::test_counter_only_yields_undecided`).
3. **Memory** persists current belief state plus full revision history
   (`tests/test_memory.py::TestBeliefStorage::test_add_and_get_belief`,
   `::TestBeliefRevision::test_revision_history_appended`).
4. **Language Interface** allows claim extraction/formatting but does not write beliefs
   (`tests/test_interface.py::TestWriteIsolation::test_interface_does_not_import_belief_storage`,
   ADR-0003's guard, and `::TestLanguageInterface::test_llm_cannot_directly_modify_beliefs`).
5. **Experience Loop** transforms observations into evidence and requests revisions
   (`tests/test_experience.py::TestExperienceLoopBasic::test_supporting_observation_increases_confidence`).

### High-level flow

1. A claim or observation is produced
   (`tests/test_interface.py::TestLanguageInterface::test_extract_claims_returns_list`).
2. Evidence is generated (or deduplicated) from that input
   (`tests/test_experience.py::TestExperienceLoopBasic::test_evidence_persisted_in_memory`,
   `::test_duplicate_evidence_not_applied_twice`).
3. `EpistemicCore` validates whether an update is eligible
   (`tests/test_core.py::TestUpdateEligibility::test_eligible_update`).
4. `EpistemicMemory` applies the update and appends a revision record
   (`tests/test_memory.py::TestBeliefRevision::test_revise_confidence`,
   `::test_revision_history_appended`).
5. Consumers query current beliefs and/or revision history
   (`tests/test_memory.py::TestBeliefStorage::test_list_beliefs_filtered_by_state`,
   `::TestBeliefRevision::test_revision_history_appended`).

Each capability above names the test that proves it, or says it has no test yet
(the README-proof convention, 10 October 2026). `.github/scripts/check_docs.py`,
run in CI, fails on a relative link in this README or under `docs/` that resolves
to nothing, a second front-matter block in any Markdown file, an ADR index that
does not list exactly the ADRs in `docs/adr/`, and a repository layout above that
names a path that is gone or misses a module.

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
