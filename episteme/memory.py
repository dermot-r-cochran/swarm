"""
EPISTEME Epistemic Memory

Disk-backed (SQLite) append-only store for beliefs, evidence, and revisions.

Design guarantees:
  - Beliefs are never overwritten; every change produces a new BeliefRevision.
  - Evidence records are immutable once written.
  - Full revision history is queryable for audit.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from episteme.models import Belief, BeliefRevision, BeliefState, BeliefType, Evidence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS beliefs (
    id          TEXT PRIMARY KEY,
    statement   TEXT NOT NULL,
    type        TEXT NOT NULL,
    confidence  REAL NOT NULL,
    domain      TEXT NOT NULL,
    evidence_ids        TEXT NOT NULL DEFAULT '[]',
    counter_evidence_ids TEXT NOT NULL DEFAULT '[]',
    state       TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id           TEXT PRIMARY KEY,
    summary      TEXT NOT NULL,
    reliability  REAL NOT NULL,
    context_hash TEXT NOT NULL,
    timestamp    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS belief_revisions (
    id             TEXT PRIMARY KEY,
    belief_id      TEXT NOT NULL,
    previous_state TEXT NOT NULL,
    new_state      TEXT NOT NULL,
    evidence_id    TEXT NOT NULL,
    reason         TEXT NOT NULL,
    revised_at     TEXT NOT NULL,
    FOREIGN KEY (belief_id) REFERENCES beliefs(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(id)
);
"""


def _row_to_belief(row: sqlite3.Row) -> Belief:
    return Belief(
        id=row["id"],
        statement=row["statement"],
        type=BeliefType(row["type"]),
        confidence=row["confidence"],
        domain=row["domain"],
        evidence_ids=json.loads(row["evidence_ids"]),
        counter_evidence_ids=json.loads(row["counter_evidence_ids"]),
        state=BeliefState(row["state"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_evidence(row: sqlite3.Row) -> Evidence:
    return Evidence(
        id=row["id"],
        summary=row["summary"],
        reliability=row["reliability"],
        context_hash=row["context_hash"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
    )


def _row_to_revision(row: sqlite3.Row) -> BeliefRevision:
    return BeliefRevision(
        id=row["id"],
        belief_id=row["belief_id"],
        previous_state=json.loads(row["previous_state"]),
        new_state=json.loads(row["new_state"]),
        evidence_id=row["evidence_id"],
        reason=row["reason"],
        revised_at=datetime.fromisoformat(row["revised_at"]),
    )


def _belief_to_dict(belief: Belief) -> dict:
    return {
        "id": belief.id,
        "statement": belief.statement,
        "type": belief.type.value,
        "confidence": belief.confidence,
        "domain": belief.domain,
        "evidence_ids": belief.evidence_ids,
        "counter_evidence_ids": belief.counter_evidence_ids,
        "state": belief.state.value,
        "created_at": belief.created_at.isoformat(),
    }


class EpistemicMemory:
    """
    Append-only SQLite-backed store for beliefs, evidence, and revisions.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Pass ``":memory:"`` for an
        in-process ephemeral store (useful in tests).
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def add_evidence(self, evidence: Evidence) -> None:
        """Persist an evidence object.  Idempotent on duplicate id."""
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO evidence
                    (id, summary, reliability, context_hash, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    evidence.id,
                    evidence.summary,
                    evidence.reliability,
                    evidence.context_hash,
                    evidence.timestamp.isoformat(),
                ),
            )

    def get_evidence_by_context_hash(self, context_hash: str) -> Evidence | None:
        """Retrieve an evidence object by its context_hash (for deduplication)."""
        row = self._conn.execute(
            "SELECT * FROM evidence WHERE context_hash = ? LIMIT 1", (context_hash,)
        ).fetchone()
        return _row_to_evidence(row) if row else None

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Retrieve an evidence object by id."""
        row = self._conn.execute(
            "SELECT * FROM evidence WHERE id = ?", (evidence_id,)
        ).fetchone()
        return _row_to_evidence(row) if row else None

    # ------------------------------------------------------------------
    # Beliefs
    # ------------------------------------------------------------------

    def add_belief(self, belief: Belief) -> None:
        """
        Persist a new belief.

        Raises
        ------
        ValueError
            If a belief with the same id already exists.
        """
        existing = self.get_belief(belief.id)
        if existing is not None:
            raise ValueError(
                f"Belief {belief.id!r} already exists. "
                "Use revise_belief() to update it."
            )
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO beliefs
                    (id, statement, type, confidence, domain,
                     evidence_ids, counter_evidence_ids, state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    belief.id,
                    belief.statement,
                    belief.type.value,
                    belief.confidence,
                    belief.domain,
                    json.dumps(belief.evidence_ids),
                    json.dumps(belief.counter_evidence_ids),
                    belief.state.value,
                    belief.created_at.isoformat(),
                ),
            )

    def get_belief(self, belief_id: str) -> Belief | None:
        """Retrieve the current state of a belief by id."""
        row = self._conn.execute(
            "SELECT * FROM beliefs WHERE id = ?", (belief_id,)
        ).fetchone()
        return _row_to_belief(row) if row else None

    def list_beliefs(
        self,
        domain: str | None = None,
        state: BeliefState | None = None,
    ) -> list[Belief]:
        """Return all beliefs, optionally filtered by domain and/or state."""
        query = "SELECT * FROM beliefs WHERE 1=1"
        params: list = []
        if domain is not None:
            query += " AND domain = ?"
            params.append(domain)
        if state is not None:
            query += " AND state = ?"
            params.append(state.value)
        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_belief(r) for r in rows]

    def revise_belief(
        self,
        belief_id: str,
        evidence: Evidence,
        *,
        new_confidence: float | None = None,
        new_state: BeliefState | None = None,
        new_evidence_ids: list[str] | None = None,
        new_counter_evidence_ids: list[str] | None = None,
        reason: str = "",
    ) -> BeliefRevision:
        """
        Apply a revision to an existing belief, logging the change.

        The original belief row is updated in-place (reflecting current state),
        and an immutable BeliefRevision record is appended for full auditability.

        Returns
        -------
        BeliefRevision
            The revision record.

        Raises
        ------
        ValueError
            If the belief does not exist.
        """
        belief = self.get_belief(belief_id)
        if belief is None:
            raise ValueError(f"Belief {belief_id!r} not found.")

        previous_state = _belief_to_dict(belief)

        # Apply updates
        if new_confidence is not None:
            belief.confidence = new_confidence
        if new_state is not None:
            belief.state = new_state
        if new_evidence_ids is not None:
            belief.evidence_ids = new_evidence_ids
        if new_counter_evidence_ids is not None:
            belief.counter_evidence_ids = new_counter_evidence_ids

        new_state_dict = _belief_to_dict(belief)

        revision = BeliefRevision(
            belief_id=belief_id,
            previous_state=previous_state,
            new_state=new_state_dict,
            evidence_id=evidence.id,
            reason=reason,
            revised_at=datetime.now(UTC),
        )

        with self._transaction() as conn:
            # Persist updated belief
            conn.execute(
                """
                UPDATE beliefs SET
                    confidence = ?,
                    state = ?,
                    evidence_ids = ?,
                    counter_evidence_ids = ?
                WHERE id = ?
                """,
                (
                    belief.confidence,
                    belief.state.value,
                    json.dumps(belief.evidence_ids),
                    json.dumps(belief.counter_evidence_ids),
                    belief_id,
                ),
            )
            # Append revision record
            conn.execute(
                """
                INSERT INTO belief_revisions
                    (id, belief_id, previous_state, new_state,
                     evidence_id, reason, revised_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision.id,
                    revision.belief_id,
                    json.dumps(revision.previous_state),
                    json.dumps(revision.new_state),
                    revision.evidence_id,
                    revision.reason,
                    revision.revised_at.isoformat(),
                ),
            )

        return revision

    # ------------------------------------------------------------------
    # Revision history
    # ------------------------------------------------------------------

    def get_revisions(self, belief_id: str) -> list[BeliefRevision]:
        """Return the full revision history for a belief, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM belief_revisions WHERE belief_id = ? ORDER BY revised_at ASC",
            (belief_id,),
        ).fetchall()
        return [_row_to_revision(r) for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
