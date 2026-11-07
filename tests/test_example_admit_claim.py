"""
Smoke test for examples/admit_claim.py, the README's *Admitting a claim*.

The example shows a caller admitting a Claim: a belief created from the
claim's text, type and domain at the uniform prior of 0.5, the claim's own
advisory confidence left behind, and only evidence moving it afterwards.
This test keeps the report true to that.
"""

import importlib.util
import sys
from pathlib import Path

from episteme import BeliefType, Claim, EpistemicMemory

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "admit_claim.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("admit_claim_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["admit_claim_example"] = module
    spec.loader.exec_module(module)
    return module


def test_admitted_claim_starts_at_the_uniform_prior_and_moves_only_on_evidence():
    lines = _load_example().main().splitlines()

    assert "suggested confidence 0.900 (advisory)" in lines[0]
    assert lines[1] == "admitted belief: confidence 0.500, evidence weight 0.0, state ACTIVE"
    assert lines[2] == "revisions after admission: 0"
    assert lines[3].startswith("one reliable observation: revised")
    after = float(lines[4].split("confidence ")[1].split(",")[0])
    assert 0.5 < after < 0.9  # evidence raised it; the claim's 0.9 was never copied
    assert lines[5] == "revisions now: 1"


def test_admit_keeps_text_type_and_domain_but_not_the_claims_confidence():
    admit = _load_example().admit
    claim = Claim(
        text="Most residents favour the ferry.",
        type=BeliefType.OPINION,
        confidence=0.97,
        domain="population",
    )
    with EpistemicMemory(":memory:") as memory:
        belief = admit(claim, memory)
        stored = memory.get_belief(belief.id)

    assert stored is not None
    assert (stored.statement, stored.type, stored.domain) == (
        claim.text,
        BeliefType.OPINION,
        "population",
    )
    assert stored.confidence == 0.5
    assert stored.alpha == stored.beta == 1.0  # Beta(1, 1), ADR-0005
