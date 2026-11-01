"""
Smoke test for examples/first_belief.py, the README's first run.

The example is the path a reader is given after installing; this test keeps
its report true to the flow it describes (two revisions, two refusals, the
history behind them) and checks that a store it is pointed at holds what
the report says.
"""

import importlib.util
import sys
from pathlib import Path

from episteme import BeliefState, EpistemicMemory

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "first_belief.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("first_belief_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["first_belief_example"] = module
    spec.loader.exec_module(module)
    return module


def test_first_run_shows_the_flow_and_its_refusals():
    report = _load_example().main([])
    lines = report.splitlines()

    assert lines[0] == "belief: confidence 0.500, evidence weight 0.0, state ACTIVE"
    assert lines[1].startswith("supporting, reliable: revised")
    assert lines[3].startswith("the same again: refused")
    assert "already been applied" in lines[3]
    assert lines[5].startswith("a rumour: refused")
    assert "below the required threshold" in lines[5]
    assert lines[7].startswith("against, reliable: revised")
    assert lines[8].endswith("state DISPUTED")

    history = lines[lines.index("revision history:") + 1 :]
    assert len(history) == 2
    first_before, _, first_after, *_ = history[0].split()
    second_before, _, second_after, *_ = history[1].split()
    assert float(first_after) > float(first_before)  # support raised it
    assert float(second_after) < float(second_before)  # evidence against lowered it
    assert second_before == first_after  # the trail is continuous


def test_first_run_on_disk_leaves_the_store_the_report_describes(tmp_path):
    db = tmp_path / "first.db"
    report = _load_example().main([str(db)])

    with EpistemicMemory(db) as store:
        (belief,) = store.list_beliefs()
        assert belief.state == BeliefState.DISPUTED
        last_described = [line for line in report.splitlines() if "belief:" in line][-1]
        assert f"confidence {belief.confidence:.3f}" in last_described
        assert len(store.get_revisions(belief.id)) == 2
        assert len(belief.evidence_ids) == 1
        assert len(belief.counter_evidence_ids) == 1
