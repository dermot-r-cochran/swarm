"""
One belief, four observations, and the trail they leave.

The core flow of the package, run end to end from a fresh install: a
belief is created at a stated prior; observations become evidence through
the ``ExperienceLoop``; the ``EpistemicCore`` decides whether each one may
revise the belief; the ``EpistemicMemory`` applies the eligible ones and
appends a revision for each. Four observations are made so that the two
kinds of refusal show beside the two kinds of revision:

1. a reliable supporting observation raises confidence;
2. the same observation submitted again is refused, because it is not new
   evidence (deduplicated by its context hash);
3. a rumour below the reliability threshold is refused;
4. reliable evidence against lowers confidence by the same rule that
   evidence for it raised it, and the belief is marked DISPUTED.

The report ends with the revision history: every change, with the
confidence before and after and the core's reason.

Nothing here says the confidence is calibrated; ADR-0005 records that the
repository holds no outcome data. The numbers are the Beta mean of the
admitted evidence, no more.

Usage::

    python examples/first_belief.py              # in-memory store
    python examples/first_belief.py first.db     # keep the store on disk
"""

from __future__ import annotations

import argparse
import sys

from episteme import Belief, BeliefType, EpistemicCore, EpistemicMemory, ExperienceLoop


def describe(belief: Belief) -> str:
    return (
        f"belief: confidence {belief.confidence:.3f}, "
        f"evidence weight {belief.evidence_weight:.1f}, state {belief.state.value}"
    )


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description="EPISTEME's core flow on one belief.")
    parser.add_argument(
        "db",
        nargs="?",
        default=":memory:",
        help="SQLite file for the store; the default keeps it in memory",
    )
    args = parser.parse_args(argv)

    lines: list[str] = []
    with EpistemicMemory(args.db) as memory:
        core = EpistemicCore(reliability_threshold=0.5, max_confidence_delta=0.3)
        loop = ExperienceLoop(core, memory)

        belief = Belief(
            statement="The footbridge will bear a crowd.",
            type=BeliefType.THEORY,
            confidence=0.5,
            domain="engineering",
        )
        memory.add_belief(belief)
        lines.append(describe(belief))

        observations = [
            ("supporting, reliable", "Load test held at twice the rated weight.", "load-test",
             0.9, True),
            ("the same again", "Load test held at twice the rated weight.", "load-test",
             0.9, True),
            ("a rumour", "Someone heard it sways.", "hearsay", 0.2, True),
            ("against, reliable", "A hanger shows a fatigue crack.", "inspection", 0.8, False),
        ]
        for label, content, source, reliability, supporting in observations:
            (result,) = loop.observe_outcome(
                content=content,
                source=source,
                reliability=reliability,
                belief_ids=[belief.id],
                domain="engineering",
                supporting=supporting,
            )
            verdict = "revised" if result.revised else "refused"
            lines.append(f"{label}: {verdict} - {result.reason}")
            current = memory.get_belief(belief.id)
            if current is None:
                # Added above, so this cannot happen; fail loudly rather than
                # print a report about a belief the store does not hold.
                raise RuntimeError(f"belief {belief.id!r} vanished from the store")
            lines.append("  " + describe(current))

        lines.append("revision history:")
        for revision in memory.get_revisions(belief.id):
            before = revision.previous_state["confidence"]
            after = revision.new_state["confidence"]
            lines.append(f"  {before:.3f} -> {after:.3f}  {revision.reason}")

    return "\n".join(lines)


if __name__ == "__main__":
    print(main(sys.argv[1:]))
