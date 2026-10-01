# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Governing rules: AGENTS.md

**Read `AGENTS.md` first and treat it as binding.** It defines the project's core principles — epistemic integrity (never invent facts, APIs, or results; say "unknown"), explicit FACT/THEORY/OPINION/FICTION separation, no silent belief updates, fail-loudly code over plausible placeholders, tests over claims, and vendor/platform neutrality. Its closing line applies to all work here: violation of these principles is a bug, not a style issue. This file adds repo mechanics; where the two could ever differ, `AGENTS.md` wins.

## What this is

EPISTEME: an epistemic foundation model architecture in Python (package `episteme`), where beliefs, uncertainty, evidence, and revision are explicit system primitives. Beliefs are typed objects with confidence and lifecycle state; evidence is validated before it can influence them; every change is persisted as an auditable revision. This is not a conventional AI/LLM repository.

## Commands

```bash
python -m pip install -e ".[dev]"   # install (Python 3.11+; dev = pytest, pytest-cov, ruff)
pytest                               # run all tests (config in pyproject.toml, testpaths=["tests"])
pytest tests/test_core.py            # one module's tests
pytest tests/test_core.py -k name    # a single test by keyword
pytest --cov=episteme --cov-fail-under=100   # what CI actually runs
ruff check .                         # lint (line-length 100, target py311)
mypy                                 # typecheck (non-strict baseline; [tool.mypy] in pyproject.toml)
```

CI (`.github/workflows/ci.yml`) runs the coverage-gated pytest command on Python 3.11/3.12/3.13 (`fail-fast: false`) plus `ruff check .` and `mypy` (a deliberately non-strict baseline — see pyproject.toml's `[tool.mypy]` note; strict mode would mean redesigning the optional-id dataclass pattern and is a separate decision). Two standing policies: the coverage figure (currently 100%) is a **ratchet, not a target** — raise it in the same change that adds the tests that earn it, never let it fall; and `ruff check .` stays clean — a `noqa` (or `type: ignore`) needs a written reason beside it.

## Architecture

Five collaborating layers (see `README.md` for the flow diagram in prose):

- `episteme/models.py` — belief, evidence, and revision dataclasses; `BeliefType` is the FACT/THEORY/OPINION/FICTION taxonomy from AGENTS.md made concrete.
- `episteme/core.py` — `EpistemicCore`, a **pure rule engine**: evaluates update eligibility (new evidence required; reliability threshold; bounded confidence change; language/repetition/consensus alone are never sufficient) and returns an `UpdateDecision` without writing anything.
- `episteme/memory.py` — `EpistemicMemory`, SQLite-backed: current belief state plus immutable, append-only `BeliefRevision` history. Beliefs are never overwritten or deleted.
- `episteme/interface.py` — `LanguageInterface`, the LLM adapter: extracts and formats `Claim` objects (proposals, not beliefs). It **cannot** write beliefs and does not import `core` or `memory`.
- `episteme/experience.py` — the observe→revise loop: turns observations into deduplicated `Evidence` (by `context_hash`), consults the core, then applies eligible updates through memory.

Flow: claim/observation → evidence → `EpistemicCore` eligibility decision → `EpistemicMemory` write + revision record → consumers query beliefs/history.

### The three ADRs (docs/adr/) and their guards

Each accepted decision has a test that fails the moment it is breached — a new ADR gets its guard test in the same change:

1. **ADR-0001, side-effect-free core** — `EpistemicCore` evaluates and returns decisions only; callers orchestrate writes through memory afterwards.
2. **ADR-0002, append-only revision memory** — every belief change appends an immutable revision; guarded by `test_memory.py::test_beliefs_never_deleted`.
3. **ADR-0003, language-interface write isolation** — belief mutations flow only through core→memory, never from language output; guarded structurally in `test_interface.py` by an AST walk asserting `episteme.interface` imports neither `episteme.core` nor `episteme.memory` (widen its `FORBIDDEN` set if new writable modules appear).

Testing mechanics — what each test file guards, the coverage-ratchet and lint policies in full, how to extend the suite, and the known gaps — live in `TestingStrategy.md`; don't duplicate them here.

## Related repositories

The map of Dermot's public repositories and what crosses between them is
`RELATED-REPOSITORIES.md` in `dermot-r-cochran/star-rangers`; this section
names only this repository's own neighbours (added 2026-09-29 at his
direction). Nothing below shares code or data with this repository; what is
shared is stated exactly.

- **`dermot-r-cochran/star-rangers`** describes this repository in public. Its
  About page (*The engineering behind the record*) names EPISTEME as lineage:
  beliefs as explicit objects with confidence and lifecycle state, evidence
  validated before it may influence them, every revision kept; and its codex
  entry *Three Disciplines of the Record* mirrors that discipline in-world.
  A change to those primitives, a rename or a retirement here makes that
  description false, so say so in the pull request and expect a follow-up
  there.
- **`dermot-r-cochran/careful-memory`** is the nearest in subject: a per-user
  belief store with derived confidence, an append-only record and
  evidence-gated writes. Independent implementations; neither imports the
  other, and AGENTS.md's rules bind only here.
- **`dermot-r-cochran/virtual-anthropology`** (The Archipelago) applies the
  same separation to a publication pipeline: every report section carries an
  epistemic category (observation, metric, hypothesis, interpretation) and
  interpretation is never generated. A resemblance of discipline, not a
  relationship; AGENTS.md binds only here (added 2026-10-01).
- **Siblings by convention:** `careful-memory`, `world-model`, `foundation-model`,
  `shadow-architect`, `visual-llm`, `swarm`, `Voting` and
  `architecture-definition-model` all carry a `TestingStrategy.md` that keeps
  testing mechanics apart from the repository's rules; six run CI coverage as a
  ratchet at the measured baseline (`swarm`, `careful-memory`, `world-model`,
  `foundation-model`, `shadow-architect`, `visual-llm`); five keep
  architecture decision records with a guard test each (`swarm`,
  `careful-memory`, `world-model`, `shadow-architect`, the ADM). When a
  convention here needs changing, those are the reference for how it is done
  in the account, and a change to the convention itself is worth landing in
  all of them or in none.
