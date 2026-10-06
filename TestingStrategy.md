# Testing Strategy

How EPISTEME is tested, what each layer guards, and the policies that keep the
gates honest. Architectural decisions the tests enforce live in `docs/adr/`.

## The governing principle

The guards in `tests/` execute without anyone remembering to run them — a test
that only runs when someone types `pytest` is a convention, and conventions
lose to convenience (the CI workflow says this in its own header). That matters
most for the **invariant guards**: the tests that exist to fail the moment a
future change breaches an ADR, not to exercise a feature.

## Layer 1 — the test suite (`tests/`, pytest)

One test file per module (plus `test_public_api.py` for the package's
exported surface), 109 tests total:

- `test_models.py` — validation invariants on the dataclasses: reliability and
  confidence bounded to [0, 1] with boundary values, string→enum coercion,
  auto-generated ids, UTC timestamps.
- `test_core.py` — `EpistemicCore`'s update eligibility, counter-evidence
  handling, confidence revision arithmetic, and adversarial-pressure
  rejection (justifications resting on language/repetition/consensus rather
  than evidence are refused).
- `test_memory.py` — the append-only store: idempotent evidence writes,
  duplicate-belief rejection, revision history appending with previous state
  preserved, and `test_beliefs_never_deleted` — the direct guard on
  **ADR-0002 (append-only revision memory)**.
- `test_experience.py` — the observe→revise loop end to end, including the
  anti-drift guards, each driven through the real loop path:
  `test_no_drift_without_evidence` (turns that record observations naming no
  belief leave its confidence byte-identical),
  `test_adversarial_repetition_does_not_drift_belief` (one observation
  submitted M times revises exactly once), the underlying `context_hash`
  dedup guard `test_duplicate_evidence_not_applied_twice`, and the
  cross-side guard that one evidence record cannot both support and dispute
  a belief.
- `test_interface.py` — **ADR-0003 (language-interface write isolation)**,
  enforced structurally: an AST walk asserts `episteme.interface` imports
  neither `episteme.core` nor `episteme.memory` at any nesting depth, so the
  invariant fails the moment the import appears, whatever the method is
  called. The `FORBIDDEN` set is the one place to widen if new writable
  modules appear.
- `test_population.py` — **ADR-0004 (population synthesis is cited
  structure, never interpretation)**: deterministic, order-independent
  clustering that keeps a minority of one; the later stance standing with
  the earlier kept as a citation and counted as a changed mind; every
  rendered position line carrying its citations; bridges; OPINION claims
  whose confidence is a share; the Rand-index `agreement` including its
  rejection of mismatched holder sets. The two guards: an AST walk asserting
  no function in `episteme.population` returns an `Interpretation` and that
  the module imports neither `episteme.core` nor `episteme.memory`, and the
  refusal of an unsigned or empty `Interpretation`.
- `test_example_archipelago.py` — pins the shape `examples/archipelago_first_fork.py`
  reads from a `virtual-anthropology` export (a fixture with `dataset.json`
  and `governance_events.json` in that shape): votes cited to their
  `VoteCast` event where one exists and to the proposal where none does,
  petitions parsed or refused loudly, goals as utterances. The example is
  outside `--cov=episteme`, so this is a smoke test of the crossing, not a
  coverage contributor.

Run: `pytest` (config in `pyproject.toml`; `testpaths = ["tests"]`).

## Layer 2 — CI (`.github/workflows/ci.yml`)

- **pytest on 3.11 / 3.12 / 3.13**, `fail-fast: false` — "fails on 3.13 only"
  and "fails everywhere" are different findings and both are worth seeing in
  one run.
- **Coverage ratchet**: the CI run is `pytest --cov=episteme
  --cov-fail-under=100`. Each figure is the *measured* coverage on the day it
  was set (95 at the gate's introduction, 2026-08-24, 369 statements, 18
  missed; 100 on 2026-08-27, 388 statements, 0 missed) — a ratchet, not a
  target: it can only be raised, never quietly fallen below. Raise it in the
  same change that adds the tests that earn it.
- **ruff lint job** — added only once the findings were fixed, per the
  workflow's original note: a permanently failing check teaches everyone to
  ignore checks, so lint arrived green on its first run. The standing policy:
  `ruff check .` stays clean; a `noqa` needs a written reason beside it (the
  one in the tree: `validate_belief` keeps raising `ValueError` because that
  is the documented contract, and changing the raised type is an API change,
  not a lint fix).

Nothing in CI depends on a cloud provider, an LLM vendor, or an orchestration
framework (AGENTS.md principle 10).

## Extending

- **A new ADR gets a guard test in the same change** — the pattern is
  ADR-0002/`test_beliefs_never_deleted` and ADR-0003/the AST import walk:
  encode the decision so a breach fails CI, not a code review.
- New module → its own `tests/test_<module>.py`, and the coverage ratchet
  rises with it.
- Behavioural fixes land with the regression test that would have caught them.

## Known gaps (candidates for next)

- The suite runs `EpistemicMemory` against `:memory:` only. An on-disk SQLite
  test would cover what that cannot: WAL persistence across close/reopen,
  rollback on a failure mid-`revise_belief`, and the append-only guarantee
  observed from a second connection.
- The two anti-drift tests are fixed-case; a `hypothesis` property suite over
  `compute_revised_confidence` / `check_adversarial_pressure` (confidence
  stays in [0, 1], no NaN, bounded movement per unit of evidence, repetition
  never compounds) would generalise them.
- Coverage sits at 100%, so the ratchet has no headroom left; the next
  raises come from new modules bringing their own tests, not from covering
  a backlog (`pytest --cov=episteme --cov-report=term-missing` confirms).
