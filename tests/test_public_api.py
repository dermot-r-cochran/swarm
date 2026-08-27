"""
Guards on the package's public surface.

Validates:
  - `__all__` is honest: every listed name is importable from the root
  - The types the public API requires as arguments are themselves exported
    (BeliefState was once importable only from episteme.models while being
    a required argument type on EpistemicMemory methods)
  - UpdateEligibilityError keeps its documented caller-facing contract
  - The package ships a py.typed marker (PEP 561)
"""

from pathlib import Path

import episteme
from episteme import BeliefState, UpdateDecision, UpdateEligibilityError


def test_all_names_are_importable():
    for name in episteme.__all__:
        assert getattr(episteme, name, None) is not None, name


def test_all_is_sorted():
    assert episteme.__all__ == sorted(episteme.__all__)


def test_api_argument_types_are_exported():
    # The types public methods take or return must be reachable from the
    # package root, not only from submodules.
    assert BeliefState.ACTIVE.value == "ACTIVE"
    assert UpdateDecision(eligible=True, reason="x").eligible is True


def test_update_eligibility_error_is_caller_facing():
    # Documented contract: the core returns decisions (ADR-0001) and never
    # raises this itself; it exists for callers to escalate with.
    assert issubclass(UpdateEligibilityError, Exception)
    assert "never raises" in (UpdateEligibilityError.__doc__ or "")


def test_py_typed_marker_ships():
    package_dir = Path(episteme.__file__).parent
    assert (package_dir / "py.typed").exists()
