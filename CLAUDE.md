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
pytest --cov=episteme --cov-fail-under=97   # what CI actually runs
ruff check .                         # lint (line-length 100, target py311)
mypy                                 # typecheck (non-strict baseline; [tool.mypy] in pyproject.toml)
```

CI (`.github/workflows/ci.yml`) runs the coverage-gated pytest command on Python 3.11/3.12/3.13 (`fail-fast: false`) plus `ruff check .` and `mypy` (a deliberately non-strict baseline — see pyproject.toml's `[tool.mypy]` note; strict mode would mean redesigning the optional-id dataclass pattern and is a separate decision). Two standing policies: the coverage figure (currently 97%) is a **ratchet, not a target** — raise it in the same change that adds the tests that earn it, never let it fall; and `ruff check .` stays clean — a `noqa` (or `type: ignore`) needs a written reason beside it.

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
