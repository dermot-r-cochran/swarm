"""
Property-based tests (hypothesis) for promises the fixed-case tests make
at a handful of points.

The first two properties are ADR-0005's, as the README states them:

- **The cap.** One evidence record moves a belief's confidence by no more
  than ``max_confidence_delta``, whatever the belief's counts, the record's
  reliability or the cap's setting, and the confidence stays a finite
  number in [0, 1]. ``test_core.py::TestBetaPosterior`` checks this across
  a fixed grid of priors; here hypothesis searches for a counterexample.
- **Direction.** Counter-evidence lowers confidence by the same rule that
  supporting evidence raises it: supporting evidence never lowers it and
  counter-evidence never raises it.

Added 2026-10-30 at Dermot's direction ("Accept all four": add hypothesis
to [dev] with a small property suite), closing the known gap that
TestingStrategy.md recorded for a property suite over the confidence
update. Calibration remains unmeasured, as ADR-0005 says; these are
properties of the arithmetic, not of the world.

The third (added 2026-11-12) is AGENTS.md principles 3, 5 and 8 through
the real ``ExperienceLoop``:

- **Repetition never compounds.** A stateful machine submits records from
  a small pool to a few beliefs, on either side, again and again, in any
  order. Each record moves a belief at most once, whichever side it came
  from and whatever came between; a resubmission changes nothing, and one
  at another reliability is refused loudly; a belief never holds more
  weight than the distinct records admitted to it; and its revision trail
  explains its state. ``test_experience.py`` checks repetition back to
  back; here hypothesis searches the interleavings. Like the others it is
  not an ADR guard. It drives one loop on one store in one thread, so it
  says nothing about concurrent observers.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    multiple,
    rule,
    run_state_machine_as_test,
)

from episteme.core import EpistemicCore
from episteme.experience import ExperienceLoop
from episteme.memory import EpistemicMemory
from episteme.models import Belief, BeliefState, BeliefType, Evidence

# Counts as a belief can hold them: the prior gives alpha + beta = 2 and
# evidence only adds, so totals below that never occur in practice; 1e-3
# keeps the search honest about small totals without wandering into
# subnormal floats, and 1e4 is far more evidence than any belief here holds.
counts = st.floats(min_value=0.0, max_value=1e4, allow_nan=False, allow_infinity=False)
unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Float rounding in alpha / (alpha + beta): a relative error of a few ulps
# on numbers no larger than 1, so 1e-9 is generous and still far below any
# cap a caller would set.
TOLERANCE = 1e-9


def _belief(alpha: float, beta: float) -> Belief:
    return Belief(
        statement="The Earth orbits the Sun.",
        type=BeliefType.FACT,
        confidence=alpha / (alpha + beta),
        domain="astronomy",
        alpha=alpha,
        beta=beta,
    )


def _evidence(reliability: float) -> Evidence:
    return Evidence(summary="An observation.", reliability=reliability, context_hash="ctx")


@given(alpha=counts, beta=counts, reliability=unit, cap=unit, supporting=st.booleans())
def test_one_record_never_moves_confidence_beyond_the_cap(
    alpha: float, beta: float, reliability: float, cap: float, supporting: bool
) -> None:
    assume(alpha + beta >= 1e-3)
    belief = _belief(alpha, beta)
    core = EpistemicCore(max_confidence_delta=cap)

    new_alpha, new_beta = core.compute_posterior(
        belief, _evidence(reliability), supporting=supporting
    )
    new_confidence = new_alpha / (new_alpha + new_beta)

    assert math.isfinite(new_confidence)
    assert 0.0 <= new_confidence <= 1.0
    assert abs(new_confidence - belief.confidence) <= cap + TOLERANCE
    # The counts stay the ones the confidence is the mean of: a Belief
    # built from them is accepted (it refuses any other confidence).
    assert _belief(new_alpha, new_beta).confidence == new_confidence


@given(alpha=counts, beta=counts, reliability=unit, cap=unit)
def test_supporting_never_lowers_and_counter_never_raises(
    alpha: float, beta: float, reliability: float, cap: float
) -> None:
    assume(alpha + beta >= 1e-3)
    belief = _belief(alpha, beta)
    core = EpistemicCore(max_confidence_delta=cap)
    evidence = _evidence(reliability)

    a, b = core.compute_posterior(belief, evidence, supporting=True)
    assert a / (a + b) >= belief.confidence - TOLERANCE

    a, b = core.compute_posterior(belief, evidence, supporting=False)
    assert a / (a + b) <= belief.confidence + TOLERANCE


# The pool of observation keys for the loop machine: three contents, each
# from two sources, so the same words arrive from more than one place. A
# small pool is the point: a long run is then mostly resubmissions.
KEYS = [
    (content, source)
    for content in ("The gauge read high.", "The gauge read low.", "The sample was clear.")
    for source in ("lab", "field")
]
THRESHOLD = EpistemicCore.DEFAULT_RELIABILITY_THRESHOLD

# Reliabilities below, at and above the threshold, so a run mixes records
# the core refuses with records it admits.
reliabilities = st.one_of(
    st.floats(min_value=0.0, max_value=THRESHOLD, exclude_max=True),
    st.just(THRESHOLD),
    st.floats(min_value=THRESHOLD, max_value=1.0, exclude_min=True),
)

# The fields of a revision's snapshots that the loop can change.
TRAIL_FIELDS = ("confidence", "alpha", "beta", "evidence_ids", "counter_evidence_ids", "state")


def _fields(belief: Belief) -> dict:
    return {
        "confidence": belief.confidence,
        "alpha": belief.alpha,
        "beta": belief.beta,
        "evidence_ids": belief.evidence_ids,
        "counter_evidence_ids": belief.counter_evidence_ids,
        "state": belief.state.value,
    }


class RepetitionThroughTheLoop(RuleBasedStateMachine):
    """The real loop, core and store against a plain record of what was admitted.

    The model is a list per belief of the keys admitted to it, in order,
    each with its side. A key is admitted to a belief only if it has never
    been admitted to that belief before, on either side, and its
    reliability meets the threshold; everything the store holds must follow
    from that list.
    """

    beliefs = Bundle("beliefs")
    observed = Bundle("observed")

    def __init__(self) -> None:
        super().__init__()
        self.memory = EpistemicMemory(":memory:")
        self.core = EpistemicCore()
        self.loop = ExperienceLoop(self.core, self.memory)
        self.priors: dict[str, Belief] = {}
        self.reliability: dict[tuple[str, str], float] = {}
        # Learned from RevisionResult.evidence_id the first time a key is seen.
        self.evidence_id: dict[tuple[str, str], str] = {}
        self.admitted: dict[str, list[tuple[tuple[str, str], bool]]] = {}

    @initialize(
        target=beliefs,
        priors=st.lists(unit, min_size=1, max_size=3),
        drawn=st.lists(reliabilities, min_size=len(KEYS), max_size=len(KEYS)),
    )
    def create(self, priors: list[float], drawn: list[float]):
        # One reliability per key for the whole run: a record always
        # reports the same reliability unless a rule says otherwise.
        self.reliability = dict(zip(KEYS, drawn, strict=True))
        for i, prior in enumerate(priors):
            belief = Belief(
                statement=f"Belief {i}.", type=BeliefType.THEORY, confidence=prior, domain="test"
            )
            self.memory.add_belief(belief)
            stored = self.memory.get_belief(belief.id)
            assert stored is not None and stored.id is not None
            self.priors[stored.id] = stored
            self.admitted[stored.id] = []
        return multiple(*self.priors)

    def _snapshot(self) -> dict[str, Belief | None]:
        return {bid: self.memory.get_belief(bid) for bid in self.priors}

    @rule(
        target=observed,
        key=st.sampled_from(KEYS),
        belief_ids=st.lists(beliefs, min_size=1, max_size=4),
        supporting=st.booleans(),
    )
    def observe(self, key: tuple[str, str], belief_ids: list[str], supporting: bool):
        before = self._snapshot()
        results = self.loop.observe_outcome(
            key[0], key[1], self.reliability[key], belief_ids, supporting=supporting
        )
        assert [r.belief_id for r in results] == belief_ids

        evidence_id = results[0].evidence_id
        assert evidence_id is not None
        assert all(r.evidence_id == evidence_id for r in results)
        # The same key is always the same record, and different keys are
        # different records, even where they share their words.
        assert self.evidence_id.setdefault(key, evidence_id) == evidence_id
        assert list(self.evidence_id.values()).count(evidence_id) == 1

        revised = set()
        for result in results:
            bid = result.belief_id
            already = any(k == key for k, _ in self.admitted[bid])
            expected = not already and self.reliability[key] >= THRESHOLD
            assert result.revised == expected, (key, supporting, result.reason)
            if expected:
                self.admitted[bid].append((key, supporting))
                revised.add(bid)

        # The core has no public accessor for its cap; this is its default.
        cap = self.core._max_confidence_delta
        for bid, then in before.items():
            now = self.memory.get_belief(bid)
            assert now is not None and then is not None
            if bid not in revised:
                # Named and refused, or not named at all: untouched.
                assert now == then
            elif supporting:
                assert then.confidence - TOLERANCE <= now.confidence
                assert now.confidence <= then.confidence + cap + TOLERANCE
            else:
                assert now.confidence <= then.confidence + TOLERANCE
                assert now.confidence >= then.confidence - cap - TOLERANCE
        return key

    @rule(
        key=observed,
        belief_ids=st.lists(beliefs, min_size=1, max_size=4),
        supporting=st.booleans(),
        other=unit,
    )
    def resubmit_with_another_reliability(
        self, key: tuple[str, str], belief_ids: list[str], supporting: bool, other: float
    ):
        # The same record, louder (or quieter), is refused loudly: evidence
        # is immutable, and the loop will not choose between two
        # reliabilities for one record.
        assume(other != self.reliability[key])
        before = self._snapshot()
        counts = {bid: len(self.memory.get_revisions(bid)) for bid in self.priors}
        with pytest.raises(ValueError, match="Evidence is immutable"):
            self.loop.observe_outcome(key[0], key[1], other, belief_ids, supporting=supporting)
        assert self._snapshot() == before
        assert {bid: len(self.memory.get_revisions(bid)) for bid in self.priors} == counts
        stored = self.memory.get_evidence(self.evidence_id[key])
        assert stored is not None and stored.reliability == self.reliability[key]

    @invariant()
    def each_belief_holds_what_was_admitted_and_no_more(self):
        for bid, prior in self.priors.items():
            belief = self.memory.get_belief(bid)
            assert belief is not None and belief.alpha is not None and belief.beta is not None
            admitted = self.admitted[bid]
            supporting = [self.evidence_id[k] for k, side in admitted if side]
            counter = [self.evidence_id[k] for k, side in admitted if not side]

            # (a) Each record once, on one side, in the order it was admitted.
            assert len(set(belief.evidence_ids)) == len(belief.evidence_ids)
            assert len(set(belief.counter_evidence_ids)) == len(belief.counter_evidence_ids)
            assert not set(belief.evidence_ids) & set(belief.counter_evidence_ids)
            assert belief.evidence_ids == supporting
            assert belief.counter_evidence_ids == counter
            # Disagreement is kept, not settled by whichever side spoke last.
            if supporting and counter:
                assert belief.state == BeliefState.DISPUTED

            # (b) A resubmission never adds a revision.
            revisions = self.memory.get_revisions(bid)
            assert len(revisions) == len(admitted)

            # (c) However many submissions arrive, a belief never holds more
            # weight than the distinct records admitted to it.
            assert prior.alpha is not None and prior.beta is not None
            gained_alpha = belief.alpha - prior.alpha
            gained_beta = belief.beta - prior.beta
            ceiling_alpha = sum(self.reliability[k] for k, side in admitted if side)
            ceiling_beta = sum(self.reliability[k] for k, side in admitted if not side)
            assert -TOLERANCE <= gained_alpha <= ceiling_alpha + TOLERANCE
            assert -TOLERANCE <= gained_beta <= ceiling_beta + TOLERANCE

            # (d) The trail explains the state: it starts from the prior,
            # each revision starts where the last ended, each cites the
            # record the model admitted at that point, and it ends here.
            state = _fields(prior)
            for revision, (key, _) in zip(revisions, admitted, strict=True):
                assert {f: revision.previous_state[f] for f in TRAIL_FIELDS} == state
                assert revision.evidence_id == self.evidence_id[key]
                state = {f: revision.new_state[f] for f in TRAIL_FIELDS}
            assert state == _fields(belief)

    def teardown(self) -> None:
        # pyproject turns warnings into errors, and an unclosed sqlite
        # connection is a ResourceWarning.
        self.memory.close()


def test_repetition_never_compounds_through_the_loop() -> None:
    # Half hypothesis's default of 100 runs (each of up to 50 steps): at 100
    # the whole suite took 7 to 12 seconds on 12 November 2026, against 3
    # before; at 50 it still killed each of eight dedup mutants in three
    # fresh searches out of three.
    run_state_machine_as_test(
        RepetitionThroughTheLoop, settings=settings(deadline=None, max_examples=50)
    )
