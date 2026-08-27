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

__all__ = [
    "Belief",
    "BeliefRevision",
    "BeliefState",
    "BeliefType",
    "Claim",
    "EpistemicCore",
    "EpistemicMemory",
    "Evidence",
    "ExperienceLoop",
    "LanguageInterface",
    "Observation",
    "RevisionResult",
    "UpdateDecision",
    "UpdateEligibilityError",
]
