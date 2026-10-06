"""
Synthesise the positions of The Archipelago's citizens.

Reads a published experiment from a checkout of
``dermot-r-cochran/virtual-anthropology`` and runs EPISTEME's population
synthesis over it. The Archipelago's citizens are simulated digital persons
with no privacy to lose and a hash-chained record of every vote and
petition, which makes them the one population a mediator can be tested on
against ground truth. Nothing here asserts anything about those citizens
beyond what their record holds, and the synthesis carries no interpretation.

What is read, and from where (the export's own files, never the simulation):

- holders and their declared values: ``dataset.json`` -> ``citizens[]``
  (``id``, ``values``);
- votes: ``governance_events.json`` -> ``proposals[].votes``, cited to the
  ``VoteCast`` event's sequence number and hash where one is recorded;
- migration petitions: ``governance_events.json`` -> ``events[]`` of type
  ``MigrationPetitioned``, the destination as the stance, the stated reason
  as the text, cited to the event's hash;
- goals: ``dataset.json`` -> ``citizens[].goals``, each goal its own topic
  with the stance ``held``, since a citizen holds several at once.

Usage::

    python examples/archipelago_first_fork.py /path/to/virtual-anthropology \
        [--experiment the-first-fork-v1] [--clusters 2]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from episteme import Citation, Holder, Utterance, agreement, cluster_by_values, render, synthesise

_PETITION = re.compile(r"petitions to migrate ([^\s:]+) → ([^\s:]+)(?:: \"(.*)\")?")


def load_population(export_dir: Path) -> tuple[list[Holder], list[Utterance]]:
    """Holders and utterances from one published Archipelago export."""
    dataset = json.loads((export_dir / "dataset.json").read_text(encoding="utf-8"))
    governance = json.loads((export_dir / "governance_events.json").read_text(encoding="utf-8"))

    holders = [
        Holder(id=c["id"], values={k: float(v) for k, v in c.get("values", {}).items()})
        for c in dataset["citizens"]
    ]
    utterances: list[Utterance] = []

    for c in dataset["citizens"]:
        # Each goal is its own topic: a citizen holds several at once, and a
        # second goal is not a change of mind about the first.
        for i, goal in enumerate(c.get("goals", [])):
            utterances.append(
                Utterance(
                    holder=c["id"],
                    topic=f"goal '{goal}'",
                    stance="held",
                    text=goal,
                    citation=Citation("dataset.json", f"citizens/{c['id']}/goals/{i}"),
                    kind="goal",
                )
            )

    vote_events = {
        (e["actor"].removeprefix("citizen:"), e["summary"].rsplit(" on ", 1)[-1].rstrip(".")): e
        for e in governance["events"]
        if e["type"] == "VoteCast"
    }
    for proposal in governance["proposals"]:
        for citizen, vote in proposal["votes"].items():
            event = vote_events.get((citizen, proposal["id"]))
            if event is None:
                citation = Citation(
                    "governance_events.json", f"proposals/{proposal['id']}/votes/{citizen}"
                )
                at = int(proposal.get("openedAtSeq", 0))
                text = f"{citizen} votes {vote} on {proposal['id']}"
            else:
                citation = Citation("events.jsonl", f"seq={event['seq']} hash={event['hash']}")
                at = int(event["seq"])
                text = event["summary"]
            utterances.append(
                Utterance(
                    holder=citizen,
                    topic=proposal["id"],
                    stance=vote,
                    text=text,
                    citation=citation,
                    kind="vote",
                    at=at,
                )
            )

    for e in governance["events"]:
        if e["type"] != "MigrationPetitioned":
            continue
        match = _PETITION.search(e["summary"])
        if match is None:
            raise ValueError(f"unrecognised petition summary at seq {e['seq']}: {e['summary']!r}")
        origin, destination, reason = match.groups()
        # The topic carries the origin, so a later petition from a different
        # island is a second position, and only a changed destination from
        # the same island counts as a changed mind.
        utterances.append(
            Utterance(
                holder=e["actor"].removeprefix("citizen:"),
                topic=f"migration from {origin}",
                stance=destination,
                text=reason or e["summary"],
                citation=Citation("events.jsonl", f"seq={e['seq']} hash={e['hash']}"),
                kind="petition",
                at=int(e["seq"]),
            )
        )

    return holders, utterances


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checkout", type=Path, help="path to a virtual-anthropology checkout")
    parser.add_argument("--experiment", default="the-first-fork-v1")
    parser.add_argument("--clusters", type=int, default=2)
    args = parser.parse_args(argv)

    export_dir = args.checkout / "the-archipelago" / "exports" / args.experiment
    holders, utterances = load_population(export_dir)
    synthesis = synthesise(holders, utterances, k=args.clusters)
    other = cluster_by_values(holders, args.clusters + 1)
    lines = [
        f"experiment: {args.experiment}",
        render(synthesis),
        (
            f"agreement with a {args.clusters + 1}-cluster reading (Rand index): "
            f"{agreement(synthesis.clusters, other):.2f}"
        ),
    ]
    report = "\n".join(lines)
    print(report)
    return report


if __name__ == "__main__":  # pragma: no cover - exercised through main() in tests
    main()
