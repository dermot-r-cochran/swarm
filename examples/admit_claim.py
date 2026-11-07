"""
Admitting a Claim: from a proposal to a belief at a uniform prior.

A ``Claim`` is what the language interface (or population synthesis)
produces: a proposal, not a belief. Its ``confidence`` is advisory, the
model's or the population's own figure, and nothing in the package copies
it into a belief (ADR-0003). Admitting a claim is the caller's act, and it
takes two steps:

1. create a ``Belief`` from the claim's text, type and domain at a stated
   prior, here the uniform 0.5 (Beta(1, 1), ADR-0005), and add it to the
   store. The claim's own confidence is not used: a fluent model saying 0.9
   is not evidence;
2. let evidence move it. Only an observation the ``EpistemicCore`` finds
   eligible revises the belief, and each revision is recorded.

The report shows the claim as proposed, the belief as admitted (evidence
weight zero, no revisions), and the belief after one reliable observation.

Usage::

    python examples/admit_claim.py
"""

from __future__ import annotations

from episteme import (
    Belief,
    BeliefType,
    Claim,
    EpistemicCore,
    EpistemicMemory,
    ExperienceLoop,
)

#: The prior an admitted claim starts from: 0.5 is the uniform Beta(1, 1),
#: which favours neither the claim nor its negation.
UNIFORM_PRIOR = 0.5


def admit(claim: Claim, memory: EpistemicMemory) -> Belief:
    """Create and store a belief for *claim* at the uniform prior.

    The claim's text, suggested type and domain are kept; its advisory
    confidence is not.
    """
    belief = Belief(
        statement=claim.text,
        type=claim.type,
        confidence=UNIFORM_PRIOR,
        domain=claim.domain,
    )
    memory.add_belief(belief)
    return belief


def describe(belief: Belief) -> str:
    return (
        f"belief: confidence {belief.confidence:.3f}, "
        f"evidence weight {belief.evidence_weight:.1f}, state {belief.state.value}"
    )


def main() -> str:
    lines: list[str] = []
    # A claim as an adapter might return it, sure of itself.
    claim = Claim(
        text="The footbridge will bear a crowd.",
        type=BeliefType.THEORY,
        confidence=0.9,
        domain="engineering",
        source="assistant",
    )
    lines.append(
        f"claim: {claim.text!r}, {claim.type.value}, suggested confidence "
        f"{claim.confidence:.3f} (advisory)"
    )

    with EpistemicMemory(":memory:") as memory:
        core = EpistemicCore(reliability_threshold=0.5, max_confidence_delta=0.3)
        loop = ExperienceLoop(core, memory)

        belief = admit(claim, memory)
        lines.append("admitted " + describe(belief))
        lines.append(f"revisions after admission: {len(memory.get_revisions(belief.id))}")

        (result,) = loop.observe_outcome(
            content="Load test held at twice the rated weight.",
            source="load-test",
            reliability=0.9,
            belief_ids=[belief.id],
            domain="engineering",
        )
        lines.append(
            f"one reliable observation: {'revised' if result.revised else 'refused'}"
            f" - {result.reason}"
        )
        current = memory.get_belief(belief.id)
        if current is None:
            # Added above, so this cannot happen; fail loudly rather than
            # report on a belief the store does not hold.
            raise RuntimeError(f"belief {belief.id!r} vanished from the store")
        lines.append("  " + describe(current))
        lines.append(f"revisions now: {len(memory.get_revisions(belief.id))}")

    return "\n".join(lines)


if __name__ == "__main__":
    print(main())
