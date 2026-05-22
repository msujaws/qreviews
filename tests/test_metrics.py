"""Metrics aggregations."""

from __future__ import annotations

from qreviews.metrics import compute_summary, daily_throughput, score_histograms
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


def test_throughput(store: Store):
    _populate(store, n_seen=3, n_posted=1)
    ts = daily_throughput(list(store.iter_for_metrics()), days=30)
    assert len(ts) >= 1
    total_seen = sum(p["seen"] for p in ts)
    total_posted = sum(p["posted"] for p in ts)
    assert total_seen == 3
    assert total_posted == 1
