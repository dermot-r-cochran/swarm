"""
Tests for the LanguageInterface adapter.

Validates:
  - LLMs produce claims, not beliefs
  - Claims cannot directly update beliefs (enforcement at API level)
  - The module has no import path to belief storage at all (ADR-0003)
  - Formatting helpers return correct epistemic language
"""

import ast
from pathlib import Path
from typing import ClassVar

import pytest

import episteme.interface
from episteme.interface import Claim, LanguageInterface
from episteme.models import BeliefType


class TestClaim:
    def test_default_claim_is_theory(self):
        c = Claim(text="The sun rises in the east.")
        assert c.type == BeliefType.THEORY

    def test_claim_confidence_range(self):
        with pytest.raises(ValueError, match="confidence"):
            Claim(text="x", confidence=1.5)

    def test_claim_type_string_coercion(self):
        c = Claim(text="x", type="FACT")
        assert c.type == BeliefType.FACT


class TestLanguageInterface:
    def setup_method(self):
        self.iface = LanguageInterface(llm_name="test-llm", default_domain="science")

    def test_extract_claims_empty_text(self):
        claims = self.iface.extract_claims("")
        assert claims == []

    def test_extract_claims_returns_list(self):
        claims = self.iface.extract_claims("Water boils at 100°C at sea level.")
        assert len(claims) == 1
        assert isinstance(claims[0], Claim)

    def test_extracted_claim_carries_source(self):
        claims = self.iface.extract_claims("Some fact.")
        assert claims[0].source == "test-llm"

    def test_extracted_claim_carries_domain(self):
        claims = self.iface.extract_claims("Some fact.")
        assert claims[0].domain == "science"

    def test_extracted_claim_is_theory(self):
        """LLM outputs are proposals (THEORY) by default."""
        claims = self.iface.extract_claims("Some claim.")
        assert claims[0].type == BeliefType.THEORY

    def test_propose_hypothesis_returns_theory(self):
        claim = self.iface.propose_hypothesis("Maybe dark matter exists.")
        assert claim.type == BeliefType.THEORY
        assert claim.confidence <= 0.5  # hypotheses are low-confidence

    def test_llm_cannot_directly_modify_beliefs(self):
        """
        The LanguageInterface has no method to write to EpistemicMemory.
        Verify the interface exposes no belief-write surface.
        """
        iface = LanguageInterface()
        write_methods = [
            m for m in dir(iface)
            if not m.startswith("_")
            and callable(getattr(iface, m))
            and any(w in m for w in ("add", "revise", "update", "delete", "write", "set"))
        ]
        assert write_methods == [], (
            f"LanguageInterface must not expose write methods: {write_methods}"
        )

    def test_format_belief_active_high_confidence(self):
        text = self.iface.format_belief("Water is H2O.", 0.95, "ACTIVE")
        assert "established" in text.lower() or "likely" in text.lower()

    def test_format_belief_unknown(self):
        text = self.iface.format_belief("X is Y.", 0.5, "UNKNOWN")
        assert "unknown" in text.lower()

    def test_format_belief_disputed(self):
        text = self.iface.format_belief("X is Y.", 0.5, "DISPUTED")
        assert "disputed" in text.lower()

    def test_format_belief_undecided(self):
        text = self.iface.format_belief("X is Y.", 0.5, "UNDECIDED")
        assert "undecided" in text.lower()

    def test_format_belief_without_uncertainty_is_bare_statement(self):
        text = self.iface.format_belief(
            "Water is H2O.", 0.95, "ACTIVE", include_uncertainty=False
        )
        assert text == "Water is H2O."

    def test_format_belief_qualifier_ladder(self):
        """Each confidence band gets its own hedging language."""
        cases = [
            (0.95, "established"),
            (0.75, "likely"),
            (0.55, "plausible"),
            (0.3, "uncertain"),
        ]
        for confidence, expected in cases:
            text = self.iface.format_belief("X is Y.", confidence, "ACTIVE")
            assert expected in text.lower(), (confidence, text)

    def test_format_unknown_query(self):
        text = self.iface.format_unknown("What is the speed of dark?")
        assert "unknown" in text.lower()

    def test_format_error(self):
        text = self.iface.format_error("revise_belief", "missing evidence")
        assert "error" in text.lower()
        assert "missing evidence" in text

    def test_label_claim_type_default(self):
        btype = self.iface.label_claim_type("The capital of France is Paris.")
        assert isinstance(btype, BeliefType)


class TestWriteIsolation:
    """
    ADR-0003 as a structural property rather than a naming convention.

    ``test_llm_cannot_directly_modify_beliefs`` above checks that no public
    method name contains a write-ish word.  That guards the current API
    surface, but it is a heuristic: a method named ``commit_claim``,
    ``persist`` or ``apply`` could import EpistemicMemory and write through
    it while passing cleanly — and those are exactly the names reached for
    when adding the orchestration shortcut ADR-0003's own "consequences"
    section says callers will want.

    What actually makes the guarantee hold is that ``episteme.interface``
    has nothing to write *through*: it imports only ``episteme.models``.
    Assert that directly, so the invariant fails the moment the import
    appears, whatever the method is called.
    """

    FORBIDDEN: ClassVar[set[str]] = {"episteme.core", "episteme.memory"}

    @staticmethod
    def _imported_modules(module) -> set[str]:
        """Every module named by an import in *module*, at any nesting depth.

        Walks the AST rather than inspecting the imported module object, so
        a deferred import inside a function body is caught too — that being
        the obvious way to reintroduce a write path without touching the
        header.
        """
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    def test_interface_does_not_import_belief_storage(self):
        imported = self._imported_modules(episteme.interface)
        breaches = imported & self.FORBIDDEN
        assert not breaches, (
            "episteme.interface must have no import path to belief storage "
            f"(ADR-0003), but imports: {sorted(breaches)}. Claims are "
            "proposals; belief mutation belongs to EpistemicCore and "
            "EpistemicMemory, orchestrated from episteme.experience."
        )

    def test_guard_detects_a_breach(self):
        """The guard above is only worth having if it can fail.

        Parse a module that *does* import belief storage — the experience
        loop, which legitimately imports both — and confirm the same check
        flags it.  Without this, a broken walker would report success
        forever.
        """
        import episteme.experience

        imported = self._imported_modules(episteme.experience)
        assert imported & self.FORBIDDEN, (
            "the import walker found no belief-storage imports in "
            "episteme.experience, which imports both — the guard in "
            "test_interface_does_not_import_belief_storage cannot be trusted"
        )
