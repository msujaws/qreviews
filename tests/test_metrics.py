"""Metrics aggregations."""

from __future__ import annotations

from qreviews.metrics import (
    _axis_hours,
    compute_summary,
    daily_throughput,
    row_to_detail,
    score_histograms,
)
from qreviews.state import Store


def _populate(store: Store, *, n_seen: int = 3, n_posted: int = 2):
    """Insert n_seen rows, of which n_posted have been posted."""
    for i in range(n_seen):
        rev_id = 1000 + i
        store.record_seen(
            revision_phid=f"PHID-DREV-{rev_id}",
            diff_phid=f"PHID-DIFF-{rev_id}",
            diff_id=rev_id,
            revision_id=rev_id,
            group_slug="ip-protection-reviewers",
            title=f"rev {rev_id}",
            author_phid="PHID-USER-x",
            revision_created_at=1716000000 + i * 60,
        )
        store.record_scored(
            revision_phid=f"PHID-DREV-{rev_id}",
            diff_phid=f"PHID-DIFF-{rev_id}",
            risk=1 if i < n_posted else 5,
            complexity=1 if i < n_posted else 6,
            risk_factors=["x"],
            complexity_factors=["y"],
            model="claude-haiku-4-5",
            usage={"input_tokens": 1000, "output_tokens": 50},
        )
        if i < n_posted:
            store.record_reviewed(
                revision_phid=f"PHID-DREV-{rev_id}",
                diff_phid=f"PHID-DIFF-{rev_id}",
                review_body="### ok\n",
                model="claude-sonnet-4-6",
                usage={"input_tokens": 5000, "output_tokens": 200},
                posted=True,
            )


def test_summary_basic(store: Store):
    _populate(store, n_seen=5, n_posted=3)
    rows = list(store.iter_for_metrics(group_slug="ip-protection-reviewers"))
    summary = compute_summary(rows, group_slug="ip-protection-reviewers")
    assert summary.revisions_seen == 5
    assert summary.revisions_scored == 5
    assert summary.revisions_posted == 3
    assert summary.coverage_pct == 60.0
    assert summary.median_risk is not None
    assert summary.estimated_cost_usd > 0


def test_histograms(store: Store):
    _populate(store, n_seen=4, n_posted=2)
    rows = list(store.iter_for_metrics())
    h = score_histograms(rows)
    assert len(h["risk"]) == 11
    assert len(h["complexity"]) == 11
    assert sum(h["risk"]) == 4
    assert sum(h["complexity"]) == 4


def test_axis_hours_is_nonlinear():
    # Each step up should add more hours than the previous step (positive
    # second derivative) — that's the whole point of the nonlinear curve.
    deltas = [_axis_hours(s + 1) - _axis_hours(s) for s in range(0, 10)]
    for i in range(1, len(deltas)):
        assert deltas[i] > deltas[i - 1], f"hours curve flattens at s={i}"
    # Sanity checks at endpoints.
    assert _axis_hours(0) == 0.1
    assert _axis_hours(10) > _axis_hours(5) * 2  # 10 saves much more than 2x of 5


def test_time_saved_counts_generated_reviews(store: Store):
    _populate(store, n_seen=5, n_posted=3)
    rows = list(store.iter_for_metrics())
    summary = compute_summary(rows)
    # _populate only writes review_body for the n_posted rows. Each has
    # risk=1, complexity=1, so per-row hours = 2 * (0.1 + 0.05 * 1^1.8).
    # Above-threshold rows (no review_body) contribute zero.
    assert summary.time_saved_hours == round(3 * (2 * _axis_hours(1)), 2)
    assert summary.time_saved_hours > 0


def test_throughput(store: Store):
    _populate(store, n_seen=3, n_posted=1)
    ts = daily_throughput(list(store.iter_for_metrics()), days=30)
    assert len(ts) >= 1
    total_seen = sum(p["seen"] for p in ts)
    total_posted = sum(p["posted"] for p in ts)
    assert total_seen == 3
    assert total_posted == 1


def _one_row(store: Store, *, critic: bool) -> dict:
    store.record_seen(
        revision_phid="PHID-DREV-critic",
        diff_phid="PHID-DIFF-critic",
        diff_id=1,
        revision_id=1,
        group_slug="ip-protection-reviewers",
        title="rev",
        author_phid="PHID-USER-x",
        revision_created_at=1716000000,
    )
    store.record_scored(
        revision_phid="PHID-DREV-critic",
        diff_phid="PHID-DIFF-critic",
        risk=1,
        complexity=1,
        risk_factors=["x"],
        complexity_factors=["y"],
        model="claude-haiku-4-5",
        usage={"input_tokens": 1000, "output_tokens": 50},
    )
    store.record_reviewed(
        revision_phid="PHID-DREV-critic",
        diff_phid="PHID-DIFF-critic",
        review_body="### ok\n",
        model="claude-sonnet-4-6",
        usage={"input_tokens": 5000, "output_tokens": 200},
        posted=True,
        critic_model="claude-haiku-4-5-20251001" if critic else "",
        critic_usage={"input_tokens": 4000, "output_tokens": 100} if critic else None,
    )
    return row_to_detail(
        next(
            r
            for r in store.iter_for_metrics(group_slug="ip-protection-reviewers")
            if r["revision_phid"] == "PHID-DREV-critic"
        )
    )


def test_critic_tokens_raise_the_estimated_cost(store: Store, tmp_db):
    without = _one_row(store, critic=False)
    other = Store(tmp_db.parent / "second.db")
    other.init_schema()
    with_critic = _one_row(other, critic=True)
    assert with_critic["estimated_cost_usd"] > without["estimated_cost_usd"]
    assert with_critic["tokens"]["critic"]["input"] == 4000
    assert with_critic["critic_model"] == "claude-haiku-4-5-20251001"


def test_skip_detail_is_surfaced(store: Store):
    store.record_seen(
        revision_phid="PHID-DREV-skip",
        diff_phid="PHID-DIFF-skip",
        diff_id=2,
        revision_id=2,
        group_slug="ip-protection-reviewers",
        title="rev",
        author_phid="PHID-USER-x",
        revision_created_at=1716000000,
    )
    store.record_reviewed(
        revision_phid="PHID-DREV-skip",
        diff_phid="PHID-DIFF-skip",
        review_body="",
        model="claude-sonnet-4-6",
        usage={},
        posted=False,
        skipped_reason="validation_parse_failed",
        skip_detail={"rejections": ["parse_failed (summary): no payload"]},
    )
    row = next(
        r
        for r in store.iter_for_metrics(group_slug="ip-protection-reviewers")
        if r["revision_phid"] == "PHID-DREV-skip"
    )
    detail = row_to_detail(row)
    assert detail["skip_detail"]["rejections"] == ["parse_failed (summary): no payload"]
