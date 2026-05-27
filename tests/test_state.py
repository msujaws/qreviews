"""SQLite state — dedup + watermarks + metrics columns."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from qreviews.state import Store


def test_init_creates_tables(store: Store):
    conn = store.connect()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "reviewed" in tables
    assert "events" in tables
    assert "poll_state" in tables
    assert "project_phids" in tables


def test_record_seen_and_dedup(store: Store):
    store.record_seen(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        diff_id=1,
        revision_id=100,
        group_slug="ip-protection-reviewers",
        title="t",
        author_phid="PHID-USER-1",
        revision_created_at=1000,
    )
    assert store.already_reviewed("PHID-DREV-1", "PHID-DIFF-1") is True
    # Different diff on same revision = NOT yet reviewed.
    assert store.already_reviewed("PHID-DREV-1", "PHID-DIFF-2") is False


def test_record_scored_updates_row(store: Store):
    store.record_seen(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        diff_id=1,
        revision_id=100,
        group_slug="ip-protection-reviewers",
        title="t",
        author_phid="PHID-USER-1",
        revision_created_at=1000,
    )
    store.record_scored(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        risk=1,
        complexity=1,
        risk_factors=["only touches docs"],
        complexity_factors=["3 LOC"],
        model="claude-haiku-4-5",
        usage={"input_tokens": 1234, "output_tokens": 56, "cache_read_input_tokens": 0,
               "cache_creation_input_tokens": 0},
    )
    row = store.get_by_revision_id(100)
    assert row["risk"] == 1
    assert row["complexity"] == 1
    assert row["scoring_input_tokens"] == 1234
    assert row["scoring_model"] == "claude-haiku-4-5"


def test_watermarks(store: Store):
    assert store.get_watermark("ip-protection-reviewers") is None
    store.set_watermark("ip-protection-reviewers", 1716000000)
    assert store.get_watermark("ip-protection-reviewers") == 1716000000
    store.set_watermark("ip-protection-reviewers", 1716100000)
    assert store.get_watermark("ip-protection-reviewers") == 1716100000


def test_phid_cache(store: Store):
    assert store.get_cached_phid("foo") is None
    store.cache_phid("foo", "PHID-PROJ-x")
    assert store.get_cached_phid("foo") == "PHID-PROJ-x"


def test_record_reviewed_posted_path(store: Store):
    store.record_seen(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        diff_id=1,
        revision_id=100,
        group_slug="ip-protection-reviewers",
        title="t",
        author_phid="PHID-USER-1",
        revision_created_at=1000,
    )
    store.record_reviewed(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        review_body="### Looks good\n\nNo findings.",
        model="claude-sonnet-4-6",
        usage={"input_tokens": 5000, "output_tokens": 200},
        posted=True,
    )
    row = store.get_by_revision_id(100)
    assert row["posted"] == 1
    assert row["posted_at"] is not None
    assert "Looks good" in row["review_body"]


def test_already_posted_on_revision(store: Store):
    # No rows yet → False.
    assert store.already_posted_on_revision("PHID-DREV-1") is False

    # A seen-but-not-posted row → still False.
    store.record_seen(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        diff_id=1,
        revision_id=100,
        group_slug="ip-protection-reviewers",
        title="t",
        author_phid="PHID-USER-1",
        revision_created_at=1000,
    )
    assert store.already_posted_on_revision("PHID-DREV-1") is False

    # Mark it posted → True.
    store.record_reviewed(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        review_body="body",
        model="claude-sonnet-4-6",
        usage={},
        posted=True,
    )
    assert store.already_posted_on_revision("PHID-DREV-1") is True

    # Different revision is unaffected.
    assert store.already_posted_on_revision("PHID-DREV-2") is False


def test_record_scored_persists_test_signals(store: Store):
    store.record_seen(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        diff_id=1,
        revision_id=100,
        group_slug="ip-protection-reviewers",
        title="t",
        author_phid="PHID-USER-1",
        revision_created_at=1000,
    )
    store.record_scored(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        risk=2,
        complexity=2,
        risk_factors=[],
        complexity_factors=[],
        model="m",
        usage={},
        test_files_changed=0,
        non_test_files_changed=2,
        in_diff_test_signal="absent",
        coverage_signal="partial",
        coverage_lookup_json='{"covered": {"dom/Foo.cpp": ["dom/test/test_foo.html"]}}',
    )
    row = store.get_by_revision_id(100)
    assert row["test_files_changed"] == 0
    assert row["non_test_files_changed"] == 2
    assert row["in_diff_test_signal"] == "absent"
    assert row["coverage_signal"] == "partial"
    assert "test_foo.html" in row["coverage_lookup_json"]


def test_record_reviewed_persists_inline_fields(store: Store):
    store.record_seen(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        diff_id=1,
        revision_id=100,
        group_slug="ip-protection-reviewers",
        title="t",
        author_phid="PHID-USER-1",
        revision_created_at=1000,
    )
    store.record_reviewed(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        review_body="summary",
        model="claude-sonnet-4-6",
        usage={},
        posted=True,
        inline_count=3,
        findings_json='[{"file_path": "a.cpp", "line": 1}]',
    )
    row = store.get_by_revision_id(100)
    assert row["inline_count"] == 3
    assert "a.cpp" in row["findings_json"]


def test_init_schema_migrates_existing_db(tmp_path: Path):
    # Build a DB with the pre-migration schema (no new columns), then run
    # init_schema and confirm the new columns appear without data loss.
    db_path = tmp_path / "legacy.db"
    legacy_schema = """
    CREATE TABLE reviewed (
        revision_phid TEXT NOT NULL,
        diff_phid     TEXT NOT NULL,
        diff_id       INTEGER NOT NULL,
        revision_id   INTEGER NOT NULL,
        group_slug    TEXT NOT NULL,
        title         TEXT,
        author_phid   TEXT,
        revision_created_at INTEGER NOT NULL,
        seen_at       INTEGER NOT NULL,
        posted        INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (revision_phid, diff_phid)
    );
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(legacy_schema)
    conn.execute(
        "INSERT INTO reviewed (revision_phid, diff_phid, diff_id, revision_id, "
        "group_slug, revision_created_at, seen_at) VALUES (?,?,?,?,?,?,?)",
        ("PHID-DREV-9", "PHID-DIFF-9", 9, 999, "g", 1000, 2000),
    )
    conn.commit()
    conn.close()

    s = Store(db_path)
    s.init_schema()
    cols = {row[1] for row in s.connect().execute("PRAGMA table_info(reviewed)").fetchall()}
    assert "test_files_changed" in cols
    assert "coverage_signal" in cols
    assert "findings_json" in cols
    # Existing row is still readable.
    row = s.get_by_revision_id(999)
    assert row is not None
    assert row["test_files_changed"] is None
    s.close()


def test_init_schema_is_idempotent(store: Store):
    # Running init_schema twice should not crash on the second ALTER TABLE.
    store.init_schema()
    store.init_schema()


def test_event_log_grows(store: Store):
    store.record_seen(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        diff_id=1,
        revision_id=100,
        group_slug="g",
        title="t",
        author_phid="a",
        revision_created_at=1000,
    )
    store.record_scored(
        revision_phid="PHID-DREV-1",
        diff_phid="PHID-DIFF-1",
        risk=1, complexity=1,
        risk_factors=[], complexity_factors=[],
        model="m", usage={},
    )
    events = store.connect().execute("SELECT event_type FROM events ORDER BY id").fetchall()
    types = [e[0] for e in events]
    assert types == ["seen", "scored"]
