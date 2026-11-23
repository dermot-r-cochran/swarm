"""
Tests for examples/edge_node.py, the worked example of ``episteme.edge``.

The mechanism's own tests are in tests/test_edge.py. These run the example
end to end from the recorded report, and live against hybrid-agent where it
is installed (skipped in CI).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "edge_node.py"
REPORT = json.loads(
    (ROOT / "tests" / "fixtures" / "hybrid_agent_rules_first_report.json").read_text(
        encoding="utf-8"
    )
)
DERIVED = "derived:checkout:before_after_deploy"


def _load():
    spec = importlib.util.spec_from_file_location("edge_node_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["edge_node_example"] = module
    spec.loader.exec_module(module)
    return module


en = _load()


def _packet(report):
    return en.packet_from_report("edge-a", None, report, sent_at="t")


# --- the worked example and the crossing ---------------------------------------


def test_worked_example_from_the_recorded_report():
    lines = en.main([]).splitlines()
    lead = "offered 0, applied 0, revised False (lead: source not verified in this context)"
    assert lines[1:4] == ["round 1:", f"  edge-a {DERIVED}: {lead}", f"  edge-b {DERIVED}: {lead}"]
    assert "  edge-a: verified True, trust 14/23" in lines
    assert any("edge-b" in line and "counted once" in line for line in lines)
    assert "refused edge-c: not enrolled" in lines
    assert "belief: confidence 0.707, revisions 2" in lines
    assert "edge-a checked wrong: verified False, beliefs to review 1" in lines


def test_runs_hybrid_agent_live_when_installed():
    pytest.importorskip("hybrid_agent")
    import hybrid_agent

    checkout = Path(hybrid_agent.__file__).resolve().parents[1]
    report = en.run_hybrid_agent(
        checkout, en.CHECKOUT_QUESTION, checkout / "examples" / "checkout_latency"
    )
    assert not any(step["called_model"] for step in report["trace"])
    assert _packet(report).items == _packet(REPORT).items
