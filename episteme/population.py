"""
EPISTEME Population Synthesis

Structure over what many holders have said, with every line cited.

A synthesis of a population's positions is a belief store about that
population, and it is held to the same rules as any other belief here:

- it is built only from recorded utterances, each carrying a citation to
  the record it came from (AGENTS.md principle 3: attributable, auditable);
- it reports structure (who holds what, in which clusters, which positions
  bridge clusters) and never a verdict; support counts are shares, not
  truth signals (principle 8: representative, not volumetric);
- minority positions are kept by construction: a cluster of one survives,
  and a position held by one holder is listed beside one held by all;
- it produces claims, never beliefs (ADR-0003's boundary applies: this
  module imports neither ``episteme.core`` nor ``episteme.memory``);
- interpretation is never generated: a ``Synthesis`` carries an
  ``Interpretation`` only when a named author supplies one (ADR-0004).

Nothing here is random. Clustering is farthest-first traversal seeded from
the lexicographically first holder, so the same input always gives the
same clusters, and a second clustering can be compared with the first by
the Rand index (``agreement``), which is how a reader tells a robust
structure from an artefact of one method.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from episteme.interface import Claim
from episteme.models import BeliefType


@dataclass(frozen=True)
class Citation:
    """Where an utterance is recorded: a source name and a locator in it."""

    source: str
    locator: str

    def __str__(self) -> str:
        return f"{self.source}#{self.locator}"


@dataclass(frozen=True)
class Utterance:
    """One recorded position of one holder on one topic.

    ``topic`` and ``stance`` are the normalised position (``"prop-0001"`` /
    ``"yes"``); ``text`` is the verbatim record. ``at`` orders utterances
    (a sequence number or tick); a holder with two stances on one topic is
    counted as having changed their mind, and the later stance stands.
    """

    holder: str
    topic: str
    stance: str
    text: str
    citation: Citation
    kind: str = "statement"
    at: int = 0

    @property
    def statement(self) -> str:
        return f"{self.topic}: {self.stance}"


@dataclass
class Holder:
    """A member of the population, with declared values on named axes."""

    id: str
    values: dict[str, float] = field(default_factory=dict)


@dataclass
class Cluster:
    """A group of holders near one seed holder in value space."""

    id: str
    seed: str
    members: tuple[str, ...]


@dataclass
class Position:
    """One statement and who holds it, with its citations."""

    statement: str
    holders: tuple[str, ...]
    support_by_cluster: dict[str, int]
    citations: tuple[Citation, ...]
    changed_minds: int


@dataclass
class Interpretation:
    """What the structure means, said by a named person, never generated."""

    author: str
    text: str

    def __post_init__(self) -> None:
        if not self.author.strip():
            raise ValueError("an Interpretation must name its author")
        if not self.text.strip():
            raise ValueError("an Interpretation must say something")


@dataclass
class Synthesis:
    """The structure of a population's positions. Carries no verdict."""

    holder_count: int
    clusters: list[Cluster]
    positions: list[Position]
    bridges: list[str]
    interpretation: Interpretation | None = None


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    axes = set(a) | set(b)
    return math.sqrt(sum((a.get(x, 0.0) - b.get(x, 0.0)) ** 2 for x in axes))


def cluster_by_values(holders: list[Holder], k: int) -> list[Cluster]:
    """Farthest-first clustering of holders by their value vectors.

    Deterministic: the first seed is the lexicographically first holder id;
    each further seed is the holder farthest from every seed so far, ties
    broken by id; each holder joins the nearest seed, ties broken by seed
    order. ``k`` is clamped to the number of holders.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    if not holders:
        return []
    by_id = {h.id: h for h in sorted(holders, key=lambda h: h.id)}
    ids = list(by_id)
    seeds = [ids[0]]
    while len(seeds) < min(k, len(ids)):
        best_id, best_gap = "", -1.0
        for hid in ids:
            if hid in seeds:
                continue
            gap = min(_distance(by_id[hid].values, by_id[s].values) for s in seeds)
            if gap > best_gap:
                best_id, best_gap = hid, gap
        seeds.append(best_id)
    members: dict[str, list[str]] = {s: [] for s in seeds}
    for hid in ids:
        nearest = min(seeds, key=lambda s: (_distance(by_id[hid].values, by_id[s].values),
                                            seeds.index(s)))
        members[nearest].append(hid)
    return [
        Cluster(id=f"c{i}", seed=s, members=tuple(members[s])) for i, s in enumerate(seeds)
    ]


def agreement(a: list[Cluster], b: list[Cluster]) -> float:
    """Rand index between two clusterings of the same holders, in [0, 1].

    1.0 means every pair of holders is together or apart in both; two
    clusterings that agree on the structure agree here, whatever they
    call the clusters. Raises if the holder sets differ.
    """
    label_a = {m: c.id for c in a for m in c.members}
    label_b = {m: c.id for c in b for m in c.members}
    if set(label_a) != set(label_b):
        raise ValueError("clusterings cover different holders")
    ids = sorted(label_a)
    if len(ids) < 2:
        return 1.0
    same = total = 0
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            total += 1
            if (label_a[x] == label_a[y]) == (label_b[x] == label_b[y]):
                same += 1
    return same / total


def synthesise(
    holders: list[Holder],
    utterances: list[Utterance],
    k: int = 2,
) -> Synthesis:
    """Build the structure of a population's positions.

    A holder's latest utterance on a topic is their position; earlier ones
    are kept as citations and counted under ``changed_minds``. A position is
    a bridge when at least two clusters spoke on its topic and every one of
    them has a holder taking it; a topic one cluster alone spoke on bridges
    nothing.
    """
    clusters = cluster_by_values(holders, k)
    cluster_of = {m: c.id for c in clusters for m in c.members}
    unknown = sorted({u.holder for u in utterances} - set(cluster_of))
    if unknown:
        raise ValueError(f"utterances from holders not in the population: {unknown}")

    by_topic_holder: dict[tuple[str, str], list[Utterance]] = {}
    for u in sorted(utterances, key=lambda u: (u.topic, u.holder, u.at)):
        by_topic_holder.setdefault((u.topic, u.holder), []).append(u)

    positions: dict[str, dict] = {}
    spoke: dict[str, set[str]] = {}
    for (topic, holder), history in by_topic_holder.items():
        latest = history[-1]
        changed = len({u.stance for u in history}) > 1
        spoke.setdefault(topic, set()).add(cluster_of[holder])
        entry = positions.setdefault(
            latest.statement,
            {"holders": [], "by_cluster": {}, "citations": [], "changed": 0},
        )
        entry["holders"].append(holder)
        entry["by_cluster"][cluster_of[holder]] = entry["by_cluster"].get(cluster_of[holder], 0) + 1
        entry["citations"].extend(u.citation for u in history)
        entry["changed"] += int(changed)

    result: list[Position] = []
    bridges: list[str] = []
    for statement in sorted(positions):
        entry = positions[statement]
        topic = statement.split(": ", 1)[0]
        pos = Position(
            statement=statement,
            holders=tuple(sorted(entry["holders"])),
            support_by_cluster=dict(sorted(entry["by_cluster"].items())),
            citations=tuple(entry["citations"]),
            changed_minds=entry["changed"],
        )
        result.append(pos)
        if len(spoke[topic]) >= 2 and set(pos.support_by_cluster) == spoke[topic]:
            bridges.append(statement)
    return Synthesis(
        holder_count=len(holders), clusters=clusters, positions=result, bridges=bridges
    )


def claims(synthesis: Synthesis, source: str = "population") -> list[Claim]:
    """Each position as a ``Claim`` proposal of type OPINION.

    ``confidence`` is the share of the population holding the position: a
    share, not a truth signal, and advisory like every Claim field. The
    citations travel in ``context`` as JSON so a caller that admits the
    claim as evidence keeps the trail.
    """
    out = []
    for pos in synthesis.positions:
        share = len(pos.holders) / synthesis.holder_count if synthesis.holder_count else 0.0
        out.append(
            Claim(
                text=pos.statement,
                type=BeliefType.OPINION,
                confidence=share,
                domain="population",
                source=source,
                context=json.dumps([str(c) for c in pos.citations]),
            )
        )
    return out


def render(synthesis: Synthesis) -> str:
    """Plain-text report: every line that claims anything cites its record."""
    lines = [f"holders: {synthesis.holder_count}"]
    for c in synthesis.clusters:
        lines.append(f"cluster {c.id} (seed {c.seed}): {', '.join(c.members)}")
    for pos in synthesis.positions:
        support = ", ".join(f"{cid}={n}" for cid, n in pos.support_by_cluster.items())
        cites = "; ".join(str(c) for c in pos.citations)
        changed = f"; changed minds: {pos.changed_minds}" if pos.changed_minds else ""
        lines.append(
            f"{pos.statement} | {len(pos.holders)} holder(s) [{support}]{changed} | {cites}"
        )
    lines.append("bridges: " + (", ".join(synthesis.bridges) if synthesis.bridges else "none"))
    if synthesis.interpretation is None:
        lines.append("interpretation: none recorded")
    else:
        lines.append(
            f"interpretation ({synthesis.interpretation.author}): {synthesis.interpretation.text}"
        )
    return "\n".join(lines)
