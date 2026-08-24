"""
EPISTEME Language Interface

Pluggable adapter between any LLM and the epistemic system.

Design invariant (spec §1.4.3):
  LLMs may generate text, label claims, and propose hypotheses—but they
  CANNOT directly update beliefs.  All belief changes must flow through
  EpistemicCore → EpistemicMemory.
"""

from __future__ import annotations

from dataclasses import dataclass

from episteme.models import BeliefType


@dataclass
class Claim:
    """
    A claim extracted from natural language by the language interface.

    Claims are *proposals*, not beliefs.  They require evidence and core
    validation before they can become or revise a belief.

    Attributes:
        text:        The claim text.
        type:        Suggested belief type (may be overridden by the core).
        confidence:  Suggested confidence from the LLM (advisory only).
        domain:      Semantic domain (advisory only).
        source:      Identifier of the LLM or process that generated the claim.
        context:     Original context text from which the claim was extracted.
    """

    text: str
    type: BeliefType = BeliefType.THEORY
    confidence: float = 0.5
    domain: str = "general"
    source: str = "unknown"
    context: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Claim confidence must be in [0, 1], got {self.confidence}"
            )
        if isinstance(self.type, str):
            self.type = BeliefType(self.type)


class LanguageInterface:
    """
    Adapter that connects a language model to the epistemic system.

    Responsibilities:
      - Accept raw text from an LLM.
      - Parse / extract Claim objects.
      - Format epistemic responses for human or LLM consumption.

    The interface deliberately exposes *no* write access to beliefs or
    evidence.  All writes are performed by the caller after consulting
    EpistemicCore.

    Parameters
    ----------
    llm_name:
        Human-readable identifier for the attached LLM (for provenance).
    default_domain:
        Domain to assign when the LLM does not specify one.
    """

    def __init__(
        self,
        llm_name: str = "generic",
        default_domain: str = "general",
    ) -> None:
        self._llm_name = llm_name
        self._default_domain = default_domain

    @property
    def llm_name(self) -> str:
        return self._llm_name

    # ------------------------------------------------------------------
    # Text → Claims
    # ------------------------------------------------------------------

    def extract_claims(
        self,
        text: str,
        context: str = "",
    ) -> list[Claim]:
        """
        Parse *text* and return a list of Claim proposals.

        This base implementation treats the entire input as a single claim
        of type THEORY with default confidence.  Subclasses or concrete
        adapters should override this method with LLM-specific parsing.

        Parameters
        ----------
        text:
            Raw text produced by the LLM.
        context:
            Original prompt or context for provenance.

        Returns
        -------
        list[Claim]
            Zero or more claim proposals.
        """
        text = text.strip()
        if not text:
            return []
        return [
            Claim(
                text=text,
                type=BeliefType.THEORY,
                confidence=0.5,
                domain=self._default_domain,
                source=self._llm_name,
                context=context,
            )
        ]

    def label_claim_type(self, text: str) -> BeliefType:
        """
        Suggest a BeliefType for a claim text.

        Base implementation returns THEORY for all inputs.  Override for
        domain-specific or LLM-driven classification.
        """
        return BeliefType.THEORY

    def propose_hypothesis(self, text: str) -> Claim:
        """
        Wrap *text* as a THEORY claim proposal.

        LLMs may propose hypotheses freely; those proposals do not become
        beliefs until validated evidence is provided.
        """
        return Claim(
            text=text,
            type=BeliefType.THEORY,
            confidence=0.3,
            domain=self._default_domain,
            source=self._llm_name,
        )

    # ------------------------------------------------------------------
    # Epistemic state → Text
    # ------------------------------------------------------------------

    def format_belief(
        self,
        statement: str,
        confidence: float,
        state: str,
        *,
        include_uncertainty: bool = True,
    ) -> str:
        """
        Render a belief as a natural-language string suitable for output.

        Parameters
        ----------
        statement:           The belief statement.
        confidence:          Confidence in [0, 1].
        state:               Belief lifecycle state (e.g., "ACTIVE").
        include_uncertainty: Whether to append confidence language.
        """
        if state == "UNKNOWN":
            return f"It is unknown whether: {statement}"
        if state == "DISPUTED":
            return f"[DISPUTED] {statement}"
        if state == "UNDECIDED":
            return f"[UNDECIDED] {statement}"

        if not include_uncertainty:
            return statement

        if confidence >= 0.9:
            qualifier = "It is established that"
        elif confidence >= 0.7:
            qualifier = "It is likely that"
        elif confidence >= 0.5:
            qualifier = "It is plausible that"
        else:
            qualifier = "It is uncertain whether"

        return f"{qualifier} {statement} (confidence: {confidence:.0%})"

    def format_unknown(self, query: str) -> str:
        """Return the canonical 'unknown' response (spec §1.7)."""
        return f"Unknown: '{query}' has no established epistemic record."

    def format_error(self, operation: str, detail: str = "") -> str:
        """Return the canonical error response (spec §1.7)."""
        msg = f"Epistemic error in '{operation}'"
        if detail:
            msg += f": {detail}"
        return msg
