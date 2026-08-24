"""
EPISTEME: An Epistemic Foundation Model

A foundation model architecture that treats beliefs, uncertainty, evidence,
and revision as first-class system primitives.
"""

from episteme.core import EpistemicCore, UpdateEligibilityError
from episteme.experience import ExperienceLoop
from episteme.interface import Claim, LanguageInterface
from episteme.memory import EpistemicMemory
from episteme.models import Belief, BeliefRevision, BeliefType, Evidence

__all__ = [
    "Belief",
    "BeliefRevision",
    "BeliefType",
    "Claim",
    "EpistemicCore",
    "EpistemicMemory",
    "Evidence",
    "ExperienceLoop",
    "LanguageInterface",
    "UpdateEligibilityError",
]
