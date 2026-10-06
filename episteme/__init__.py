"""
EPISTEME: An Epistemic Foundation Model

A foundation model architecture that treats beliefs, uncertainty, evidence,
and revision as first-class system primitives.
"""

from episteme.core import EpistemicCore, UpdateDecision, UpdateEligibilityError
from episteme.experience import ExperienceLoop, Observation, RevisionResult
from episteme.interface import Claim, LanguageInterface
from episteme.memory import EpistemicMemory
from episteme.models import Belief, BeliefRevision, BeliefState, BeliefType, Evidence
from episteme.population import (
    Citation,
    Cluster,
    Holder,
    Interpretation,
    Position,
    Synthesis,
    Utterance,
    agreement,
    claims,
    cluster_by_values,
    render,
    synthesise,
)

__all__ = [
    "Belief",
    "BeliefRevision",
    "BeliefState",
    "BeliefType",
    "Citation",
    "Claim",
    "Cluster",
    "EpistemicCore",
    "EpistemicMemory",
    "Evidence",
    "ExperienceLoop",
    "Holder",
    "Interpretation",
    "LanguageInterface",
    "Observation",
    "Position",
    "RevisionResult",
    "Synthesis",
    "UpdateDecision",
    "UpdateEligibilityError",
    "Utterance",
    "agreement",
    "claims",
    "cluster_by_values",
    "render",
    "synthesise",
]
