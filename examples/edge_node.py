"""
A worked example of the edge node (``episteme.edge``; ADR-0006 and ADR-0007).

Usage::

    python examples/edge_node.py /path/to/hybrid-agent

runs hybrid-agent once on its worked example and uses the report as the hub's
own observation and as two peers' packets over two rounds: the peers' items
are leads in round one, verified by consistency with the hub's own data, and
weighted in round two; a ground-truth check then finds one wrong and
suspends it. Without a path it uses the report recorded in
``tests/fixtures/hybrid_agent_rules_first_report.json``.

Running hybrid-agent lives here, not in the package: the package reads a
report and gains no dependency on hybrid-agent (ADR-0006).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from episteme import Belief, BeliefType, EpistemicMemory
from episteme.edge import (
    EdgeNode,
    HmacSha256,
    P95Check,
    Policy,
    Route,
    Signer,
    SourceLedger,
    p95_rose,
    packet_from_report,
)

#: The question the worked example asks hybrid-agent.
CHECKOUT_QUESTION = "Why did checkout p95 latency go up after the latest deploy?"

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "hybrid_agent_rules_first_report.json"
)


def run_hybrid_agent(
    hybrid_agent_dir: Path, question: str, evidence_dir: Path, *, python: str = sys.executable
) -> dict:
    """Run hybrid-agent locally with ``--rules-first`` and return its JSON report.

    A subprocess, not an import: the node carries hybrid-agent's report and
    does not turn it into a library or a service (ADR-0006).
    """
    done = subprocess.run(
        [
            python,
            "-m",
            "hybrid_agent",
            question,
            "--evidence",
            str(evidence_dir),
            "--rules-first",
            "--json",
        ],
        cwd=hybrid_agent_dir,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(done.stdout)


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("hybrid_agent", nargs="?", type=Path,
                        help="a checkout of dermot-r-cochran/hybrid-agent, installed")
    args = parser.parse_args(argv)

    if args.hybrid_agent is None:
        report = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source = f"recorded report ({FIXTURE.name})"
    else:
        evidence = args.hybrid_agent / "examples" / "checkout_latency"
        report = run_hybrid_agent(args.hybrid_agent, CHECKOUT_QUESTION, evidence)
        source = f"hybrid-agent --rules-first in {args.hybrid_agent}"

    # The worked example's own settings. They are inputs to this run, not part
    # of the mechanism, and another node in another context would set its own.
    policy = Policy(
        ground_truth_weight=Fraction(1), consistency_weight=Fraction(1, 2),
        failure_multiple=Fraction(2), discount=Fraction(9, 10), ceiling=Fraction(9, 10),
        own_reliability=Fraction(4, 5), cap=Fraction(2), audit_rate=Fraction(1, 5),
        drift_window=5,
    )
    check = P95Check(spread_pp=Fraction(75), drift_limit_pp=Fraction(10))
    ledger = SourceLedger(policy)
    # edge-a signs, as an integrity check; edge-b does not. Neither changes trust.
    ledger.enrol("edge-a", HmacSha256(b"secret-edge-a"), reason="worked example")
    ledger.enrol("edge-b", reason="worked example")
    ledger.declare_group("same-firmware", ["edge-a", "edge-b"],
                         reason="same build and the same metrics source")
    signers: dict[str, Signer | None] = {
        "edge-a": HmacSha256(b"secret-edge-a"), "edge-b": None, "edge-c": None
    }

    memory = EpistemicMemory()
    belief = Belief("checkout p95 latency regressed after deploy 4.12.0",
                    BeliefType.THEORY, 0.5, "checkout")
    memory.add_belief(belief)
    assert belief.id is not None
    kind = "compute.compare_windows"
    hub = EdgeNode("hub", memory, ledger, [Route(kind, belief.id, p95_rose)],
                   comparators={kind: check.degree},
                   deviations={kind: (check.deviation, check.drift_limit_pp)},
                   audit_salt=b"worked-example")

    lines = [f"report: {source}"]
    for round_no in (1, 2):
        if round_no == 1:
            hub.observe_own(report)  # the hub's own run of the same investigation
        for node_id in ("edge-a", "edge-b", "edge-c"):
            hub.receive(packet_from_report(node_id, signers[node_id], report,
                                           sent_at="2026-11-23T12:00:00Z"))
        lines.append(f"round {round_no}:")
        for o in hub.close_round():
            lines.append(f"  {o.node_id} {o.item_id}: offered {o.offered}, applied {o.applied}, "
                         f"revised {o.revised} ({o.reason})")
        for node_id in ("edge-a", "edge-b"):
            lines.append(f"  {node_id}: verified {ledger.is_verified(node_id, kind)}, "
                         f"trust {ledger.trust(node_id, kind)}")
    for node_id, integrity in hub.received[:2]:
        lines.append(f"{node_id}: integrity {integrity}")
    lines.append(f"refused edge-c: {dict(hub.refused)['edge-c']}")
    after = memory.get_belief(belief.id)
    assert after is not None
    lines.append(f"belief: confidence {after.confidence:.3f}, "
                 f"revisions {len(memory.get_revisions(belief.id))}")
    review = hub.check_ground_truth("edge-a", "derived:checkout:before_after_deploy",
                                    correct=False, against="a person's inspection")
    lines.append(f"edge-a checked wrong: verified {ledger.is_verified('edge-a', kind)}, "
                 f"beliefs to review {len(review)}")
    lines.append(f"proposals held, not believed: {len(hub.claims)}")
    memory.close()
    return "\n".join(lines)


if __name__ == "__main__":
    print(main())
