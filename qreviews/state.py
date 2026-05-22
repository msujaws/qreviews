"""SQLite-backed state + metrics store.

WAL mode is enabled so the dashboard can read while the poller writes. The
schema is deliberately denormalized — one row per (revision_phid, diff_phid)
that captures everything the dashboard needs without joins.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS reviewed (
    revision_phid           TEXT NOT NULL,
    diff_phid               TEXT NOT NULL,
    diff_id                 INTEGER NOT NULL,
    revision_id             INTEGER NOT NULL,
    group_slug              TEXT NOT NULL,
    title                   TEXT,
    author_phid             TEXT,
    revision_created_at     INTEGER NOT NULL,
    seen_at                 INTEGER NOT NULL,
    scored_at               INTEGER,
    risk                    INTEGER,
    complexity              INTEGER,
    risk_factors_json       TEXT,
    complexity_factors_json TEXT,
    scoring_model           TEXT,
    scoring_input_tokens    INTEGER DEFAULT 0,
    scoring_output_tokens   INTEGER DEFAULT 0,
    scoring_cache_read      INTEGER DEFAULT 0,
    scoring_cache_write     INTEGER DEFAULT 0,
    reviewed_at             INTEGER,
    review_model            TEXT,
    review_input_tokens     INTEGER DEFAULT 0,
    review_output_tokens    INTEGER DEFAULT 0,
    review_cache_read       INTEGER DEFAULT 0,
    review_cache_write      INTEGER DEFAULT 0,
    review_tool_calls       INTEGER DEFAULT 0,
    review_body             TEXT,
    posted                  INTEGER NOT NULL DEFAULT 0,
    posted_at               INTEGER,
    skipped_reason          TEXT,
    final_status            TEXT,
    closed_at               INTEGER,
    human_first_response_at INTEGER,
    PRIMARY KEY (revision_phid, diff_phid)
);

CREATE INDEX IF NOT EXISTS idx_reviewed_group ON reviewed(group_slug);
CREATE INDEX IF NOT EXISTS idx_reviewed_revision_id ON reviewed(revision_id);
CREATE INDEX IF NOT EXISTS idx_reviewed_seen_at ON reviewed(seen_at);
CREATE INDEX IF NOT EXISTS idx_reviewed_posted ON reviewed(posted);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_phid TEXT NOT NULL,
    revision_id   INTEGER,
    group_slug    TEXT,
    event_type    TEXT NOT NULL,
    ts            INTEGER NOT NULL,
    detail_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_rev ON events(revision_phid);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS poll_state (
    group_slug    TEXT PRIMARY KEY,
    last_modified INTEGER NOT NULL,
    last_poll_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS project_phids (
    slug TEXT PRIMARY KEY,
    phid TEXT NOT NULL,
    resolved_at INTEGER NOT NULL
);
"""


class Store:
    """Thin SQLite wrapper. One Store per process; thread-safe enough for
    single-writer / multi-reader (WAL)."""

    def __init__(self, db_path: str | Path = "qreviews.db"):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------ connection

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                isolation_level=None,  # autocommit; we manage transactions explicitly
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def init_schema(self) -> None:
        conn = self.connect()
        conn.executescript(SCHEMA)

    @contextmanager
    def txn(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------ dedup

    def already_reviewed(self, revision_phid: str, diff_phid: str) -> bool:
        cur = self.connect().execute(
            "SELECT 1 FROM reviewed WHERE revision_phid=? AND diff_phid=?",
            (revision_phid, diff_phid),
        )
        return cur.fetchone() is not None

    # ------------------------------------------------------------ writes

    def record_seen(
        self,
        *,
        revision_phid: str,
        diff_phid: str,
        diff_id: int,
        revision_id: int,
        group_slug: str,
        title: str,
        author_phid: str,
        revision_created_at: int,
    ) -> None:
        now = int(time.time())
        with self.txn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO reviewed (
                    revision_phid, diff_phid, diff_id, revision_id, group_slug,
                    title, author_phid, revision_created_at, seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_phid,
                    diff_phid,
                    diff_id,
                    revision_id,
                    group_slug,
                    title,
                    author_phid,
                    revision_created_at,
                    now,
                ),
            )
            self._add_event(
                conn,
                revision_phid=revision_phid,
                revision_id=revision_id,
                group_slug=group_slug,
                event_type="seen",
                detail={"diff_id": diff_id},
            )

    def record_scored(
        self,
        *,
        revision_phid: str,
        diff_phid: str,
        risk: int,
        complexity: int,
        risk_factors: list[str],
        complexity_factors: list[str],
        model: str,
        usage: dict[str, int],
    ) -> None:
        now = int(time.time())
        with self.txn() as conn:
            conn.execute(
                """
                UPDATE reviewed SET
                    scored_at=?, risk=?, complexity=?,
                    risk_factors_json=?, complexity_factors_json=?,
                    scoring_model=?,
                    scoring_input_tokens=?, scoring_output_tokens=?,
                    scoring_cache_read=?, scoring_cache_write=?
                WHERE revision_phid=? AND diff_phid=?
                """,
                (
                    now,
                    risk,
                    complexity,
                    json.dumps(risk_factors),
                    json.dumps(complexity_factors),
                    model,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    usage.get("cache_read_input_tokens", 0),
                    usage.get("cache_creation_input_tokens", 0),
                    revision_phid,
                    diff_phid,
                ),
            )
            row = conn.execute(
                "SELECT revision_id, group_slug FROM reviewed WHERE revision_phid=? AND diff_phid=?",
                (revision_phid, diff_phid),
            ).fetchone()
            self._add_event(
                conn,
                revision_phid=revision_phid,
                revision_id=row["revision_id"] if row else None,
                group_slug=row["group_slug"] if row else None,
                event_type="scored",
                detail={"risk": risk, "complexity": complexity},
            )

    def record_reviewed(
        self,
        *,
        revision_phid: str,
        diff_phid: str,
        review_body: str,
        model: str,
        usage: dict[str, int],
        posted: bool,
        skipped_reason: str | None = None,
        tool_calls: int = 0,
    ) -> None:
        now = int(time.time())
        with self.txn() as conn:
            conn.execute(
                """
                UPDATE reviewed SET
                    reviewed_at=?, review_body=?, review_model=?,
                    review_input_tokens=?, review_output_tokens=?,
                    review_cache_read=?, review_cache_write=?,
                    review_tool_calls=?,
                    posted=?, posted_at=?, skipped_reason=?
                WHERE revision_phid=? AND diff_phid=?
                """,
                (
                    now,
                    review_body,
                    model,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    usage.get("cache_read_input_tokens", 0),
                    usage.get("cache_creation_input_tokens", 0),
                    tool_calls,
                    1 if posted else 0,
                    now if posted else None,
                    skipped_reason,
                    revision_phid,
                    diff_phid,
                ),
            )
            row = conn.execute(
                "SELECT revision_id, group_slug FROM reviewed WHERE revision_phid=? AND diff_phid=?",
                (revision_phid, diff_phid),
            ).fetchone()
            self._add_event(
                conn,
                revision_phid=revision_phid,
                revision_id=row["revision_id"] if row else None,
                group_slug=row["group_slug"] if row else None,
                event_type="posted" if posted else "skipped",
                detail={"skipped_reason": skipped_reason} if skipped_reason else {},
            )

    def record_skipped(
        self,
        *,
        revision_phid: str,
        diff_phid: str,
        reason: str,
    ) -> None:
        """Record a skip that happens BEFORE scoring (e.g. oversized diff)."""
        now = int(time.time())
        with self.txn() as conn:
            conn.execute(
                """
                UPDATE reviewed SET posted=0, skipped_reason=?, reviewed_at=?
                WHERE revision_phid=? AND diff_phid=?
                """,
                (reason, now, revision_phid, diff_phid),
            )
            row = conn.execute(
                "SELECT revision_id, group_slug FROM reviewed WHERE revision_phid=? AND diff_phid=?",
                (revision_phid, diff_phid),
            ).fetchone()
            self._add_event(
                conn,
                revision_phid=revision_phid,
                revision_id=row["revision_id"] if row else None,
                group_slug=row["group_slug"] if row else None,
                event_type="skipped",
                detail={"reason": reason},
            )

    def update_final_status(
        self,
        revision_phid: str,
        *,
        final_status: str,
        closed_at: int | None,
        human_first_response_at: int | None,
    ) -> None:
        with self.txn() as conn:
            conn.execute(
                """
                UPDATE reviewed SET
                    final_status=?,
                    closed_at=COALESCE(?, closed_at),
                    human_first_response_at=COALESCE(human_first_response_at, ?)
                WHERE revision_phid=?
                """,
                (final_status, closed_at, human_first_response_at, revision_phid),
            )

    # ------------------------------------------------------------ events

    def _add_event(
        self,
        conn: sqlite3.Connection,
        *,
        revision_phid: str,
        revision_id: int | None,
        group_slug: str | None,
        event_type: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO events (revision_phid, revision_id, group_slug, event_type, ts, detail_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                revision_phid,
                revision_id,
                group_slug,
                event_type,
                int(time.time()),
                json.dumps(detail or {}),
            ),
        )

    # ------------------------------------------------------------ watermarks

    def get_watermark(self, group_slug: str) -> int | None:
        row = self.connect().execute(
            "SELECT last_modified FROM poll_state WHERE group_slug=?", (group_slug,)
        ).fetchone()
        return int(row["last_modified"]) if row else None

    def set_watermark(self, group_slug: str, last_modified: int) -> None:
        now = int(time.time())
        with self.txn() as conn:
            conn.execute(
                """
                INSERT INTO poll_state (group_slug, last_modified, last_poll_at)
                VALUES (?, ?, ?)
                ON CONFLICT(group_slug) DO UPDATE SET
                    last_modified=excluded.last_modified,
                    last_poll_at=excluded.last_poll_at
                """,
                (group_slug, last_modified, now),
            )

    # ------------------------------------------------------------ phid cache

    def get_cached_phid(self, slug: str) -> str | None:
        row = self.connect().execute(
            "SELECT phid FROM project_phids WHERE slug=?", (slug,)
        ).fetchone()
        return row["phid"] if row else None

    def cache_phid(self, slug: str, phid: str) -> None:
        now = int(time.time())
        with self.txn() as conn:
            conn.execute(
                """
                INSERT INTO project_phids (slug, phid, resolved_at) VALUES (?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET phid=excluded.phid, resolved_at=excluded.resolved_at
                """,
                (slug, phid, now),
            )

    # ------------------------------------------------------------ queries (used by dashboard / metrics)

    def list_recent(
        self,
        *,
        group_slug: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM reviewed"
        params: list[Any] = []
        if group_slug:
            sql += " WHERE group_slug=?"
            params.append(group_slug)
        sql += " ORDER BY seen_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return list(self.connect().execute(sql, params).fetchall())

    def get_by_revision_id(self, revision_id: int) -> sqlite3.Row | None:
        return self.connect().execute(
            "SELECT * FROM reviewed WHERE revision_id=? ORDER BY seen_at DESC LIMIT 1",
            (revision_id,),
        ).fetchone()

    def revisions_to_backfill(self, *, batch: int = 50) -> list[sqlite3.Row]:
        """Rows that the poller should re-check for status/human-response updates."""
        return list(
            self.connect().execute(
                """
                SELECT revision_phid, revision_id, posted_at, seen_at FROM reviewed
                WHERE (final_status IS NULL OR final_status NOT IN ('published','abandoned'))
                ORDER BY seen_at DESC
                LIMIT ?
                """,
                (batch,),
            ).fetchall()
        )

    def iter_for_metrics(self, *, group_slug: str | None = None) -> Iterable[sqlite3.Row]:
        sql = "SELECT * FROM reviewed"
        params: list[Any] = []
        if group_slug:
            sql += " WHERE group_slug=?"
            params.append(group_slug)
        return self.connect().execute(sql, params)
