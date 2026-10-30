"""
Property-based tests (hypothesis) for promises the fixed-case tests make
at a handful of points.

Both properties are ADR-0005's, as the README states them:

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
"""

from __future__ import annotations

import math

from hypothesis import assume, given
from hypothesis import strategies as st

from episteme.core import EpistemicCore
from episteme.models import Belief, BeliefType, Evidence

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
