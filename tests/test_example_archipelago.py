"""
Smoke test for examples/archipelago_first_fork.py against a fixture shaped
like a published Archipelago export (dataset.json, governance_events.json).

The example is the data crossing between this repository and
dermot-r-cochran/virtual-anthropology; this test pins the shape it reads,
so a change in the export format fails here rather than at the next run.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "archipelago_first_fork.py"


def _load_example():
    spec = importlib.util.spec_from_file_location("archipelago_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["archipelago_example"] = module
    spec.loader.exec_module(module)
    return module


def _write_export(root: Path, *, with_vote_event: bool = True, bad_petition: bool = False):
    export = root / "the-archipelago" / "exports" / "the-first-fork-v1"
    export.mkdir(parents=True)
    dataset = {
        "citizens": [
            {"id": "cit-0001", "values": {"autonomy": 0.4, "tradition": 0.2},
             "goals": ["chart the shoals"]},
            {"id": "cit-0002", "values": {"autonomy": -0.5, "tradition": 0.9}, "goals": []},
            {"id": "cit-0003", "values": {"autonomy": 0.9, "tradition": -0.9}},
        ]
    }
    events = [
        {"seq": 3, "type": "ProposalSubmitted", "actor": "citizen:cit-0001",
         "summary": "x proposes", "hash": "h3"},
        {"seq": 13, "type": "MigrationPetitioned", "actor": "citizen:cit-0001",
         "summary": ("Orin (cit-0001) petitions to migrate continuity → fork: "
                     "\"To study branching law.\""
                     if not bad_petition else "Orin wanders off"),
         "hash": "h13"},
    ]
    if with_vote_event:
        events.append({"seq": 6, "type": "VoteCast", "actor": "citizen:cit-0001",
                       "summary": "Orin (cit-0001) votes yes on prop-0001.", "hash": "h6"})
    governance = {
        "proposals": [
            {"id": "prop-0001", "votes": {"cit-0001": "yes", "cit-0002": "no"}, "openedAtSeq": 3}
        ],
        "events": events,
    }
    (export / "dataset.json").write_text(json.dumps(dataset), encoding="utf-8")
    (export / "governance_events.json").write_text(json.dumps(governance), encoding="utf-8")
    return export


def test_example_reads_an_export_and_cites_the_record(tmp_path):
    example = _load_example()
    _write_export(tmp_path)
    report = example.main([str(tmp_path), "--clusters", "2"])
    assert "prop-0001: yes" in report and "prop-0001: no" in report
    assert "seq=6 hash=h6" in report  # the vote cited to its event
    assert "proposals/prop-0001/votes/cit-0002" in report  # no event: cited to the proposal
    assert "migration from continuity: fork" in report
    assert "goal 'chart the shoals': held" in report
    assert "interpretation: none recorded" in report
    assert "Rand index" in report


def test_example_without_vote_events_still_cites(tmp_path):
    example = _load_example()
    export = _write_export(tmp_path, with_vote_event=False)
    holders, utterances = example.load_population(export)
    votes = [u for u in utterances if u.kind == "vote"]
    assert len(votes) == 2 and all(u.citation.source == "governance_events.json" for u in votes)
    assert len(holders) == 3


def test_example_fails_loudly_on_an_unrecognised_petition(tmp_path):
    example = _load_example()
    export = _write_export(tmp_path, bad_petition=True)
    with pytest.raises(ValueError, match="unrecognised petition"):
        example.load_population(export)
