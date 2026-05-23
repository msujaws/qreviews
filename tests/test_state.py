"""SQLite state — dedup + watermarks + metrics columns."""

from __future__ import annotations

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
