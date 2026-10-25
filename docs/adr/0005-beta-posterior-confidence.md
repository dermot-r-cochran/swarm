# ADR-0005: Belief confidence is the mean of a reliability-weighted Beta posterior

- **Status:** Accepted
- **Date:** 2026-10-25

## Context

Until this decision a belief's confidence was one stored number, revised by
`old + reliability × (1 − old)` for supporting evidence. Three things followed
from that, each recorded here as FACT about the code before this change:

- **Counter-evidence never lowered confidence.** It moved the belief to
  `DISPUTED` or `UNDECIDED` and left the number where it was. The opposing rule,
  `old × (1 − reliability)`, was written in the docstring of
  `compute_revised_confidence` and implemented nowhere. A belief at 0.97 stayed
  at 0.97 after reliable evidence against it.
- **The number could not say how much evidence it rested on.** A belief at 0.7
  after one observation and one at 0.7 after twenty looked the same.
- **The update was monotone.** Supporting evidence only ever raised confidence
  towards 1; nothing pulled it back.

`dermot-r-cochran/careful-memory` (its ADR-0001) already models confidence as
the mean of a Beta(α, β) distribution, with no shared code. Dermot chose that
direction for this repository on 25 October 2026.

## Decision

A belief's confidence is the mean of a Beta posterior:

```
confidence = α / (α + β)
```

- **The prior.** A new belief created at confidence `c` starts from
  Beta(2c, 2(1 − c)), a prior worth `PRIOR_STRENGTH = 2` observations; 0.5 is
  the uniform Beta(1, 1). Creating a belief at a confidence is therefore
  stating a prior, which is an assumption, and the counts record it as one.
- **The update.** Supporting evidence adds its reliability to α;
  counter-evidence adds its reliability to β (`EpistemicCore.compute_posterior`).
  Counter-evidence lowers confidence by the same rule that supporting evidence
  raises it. The disagreement is still kept: the state still becomes
  `DISPUTED` or `UNDECIDED`, and the counter-evidence ids are still recorded.
- **The cap.** The weight one record adds is reduced, never the mean alone, so
  that the mean moves by no more than `max_confidence_delta`. The counts stored
  are always the ones the confidence is the mean of.
- **Derived, never written.** `Belief` refuses a confidence that is not the mean
  of its counts, and `EpistemicMemory.revise_belief` takes `new_alpha` and
  `new_beta` and has no confidence parameter. `Belief.evidence_weight`
  (`α + β − PRIOR_STRENGTH`) reports how much evidence a belief rests on,
  beside its confidence.
- **Older databases.** The `beliefs` table gains nullable `alpha` and `beta`
  columns. A row written before this decision has them NULL and is read back
  with its prior derived from its stored confidence; no row is rewritten.

## How this meets AGENTS.md

Principles 5 and 8 forbid drift by exposure and treating volume as a truth
signal. The counts accumulate evidence, so the decision has to show why they do
not accumulate volume:

- what adds to α or β is evidence the core has already admitted: new, at or
  above the reliability threshold, and deduplicated by `context_hash`, so one
  observation submitted many times still revises once
  (`test_adversarial_repetition_does_not_drift_belief`, unchanged);
- the cap bounds what any one record can do;
- evidence against counts exactly as much as evidence for, so a belief can be
  argued down as well as up, which the previous rule could not do;
- `evidence_weight` makes the amount of evidence visible instead of folding it
  silently into the confidence.

What the counts do **not** do is model correlation between records: two
distinct records that share an unseen common cause count as two. That was true
before this decision as well, and it is recorded here as a known limit, not
solved.

## What this does not claim

- **Reliability as weight, and a prior strength of 2, are design choices
  (THEORY), not calibrated constants.** Nothing in this repository shows that a
  belief at 0.8 is right four times in five. That is calibration, an empirical
  property that needs beliefs paired with outcomes, and the repository holds no
  such data. Until it does, confidence is a well-formed summary of the admitted
  evidence, not a measured probability.
- The Beta mean is the only statistic used. Credible intervals are computable
  from the counts but are not implemented.

## Consequences

- Counter-evidence lowers confidence, by a test through the real loop
  (`test_experience.py::TestBetaConfidenceInTheLoop::test_counter_evidence_lowers_confidence`).
- Equal evidence each way returns a belief to where it started while recording
  how much evidence it now rests on
  (`::test_weight_of_evidence_is_kept_beside_confidence`).
- **Breaking change:** `revise_belief(new_confidence=...)` is replaced by
  `revise_belief(new_alpha=..., new_beta=...)`. `compute_revised_confidence`
  keeps its signature and now returns the supporting posterior mean.
- **Guards:** `test_models.py::TestBetaConfidence::test_confidence_cannot_be_asserted_apart_from_counts`
  fails if a belief accepts a confidence its counts do not give, and
  `test_memory.py::TestBetaCounts::test_confidence_has_no_write_path_of_its_own`
  fails if `revise_belief` gains a confidence parameter.
