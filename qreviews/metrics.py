"""Metrics aggregations consumed by the CLI and the dashboard.

All aggregations operate on raw rows from `Store.iter_for_metrics`. Keeps the
SQL in `state.py` simple and the analytics easy to test.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from statistics import median

from qreviews.pricing import estimate_cost_usd

# --------------------------------------------------------------------- helpers


# Hours a human reviewer would otherwise have spent per score axis.
# Nonlinear (power 1.8) so high-complexity / high-risk revisions save
# disproportionately more time than trivial ones — matches the actual
# review burden, where the last 20% of revisions consume most attention.
#   s=0 → 0.10h    s=3 → 0.46h    s=7 → 2.13h
#   s=1 → 0.15h    s=5 → 1.15h    s=10 → 3.66h
def _axis_hours(score: int | None) -> float:
    if score is None:
        return 0.0
    return 0.1 + 0.05 * (max(0, int(score)) ** 1.8)


def _row_time_saved_hours(row) -> float:
    """Hours saved (or that would have been saved in dry-run) when the bot
    generated an advisory review for a revision.

    Sum of nonlinear per-axis hours for risk and complexity. Counted
    whenever the bot produced a review body — i.e. the revision passed the
    score gate and the bot completed a review pass. Includes dry-run
    reviews so the dashboard surfaces projected value before going live.
    Above-threshold / skipped / error rows have an empty review_body and
    contribute zero.
    """
    if not row["review_body"]:
        return 0.0
    return _axis_hours(row["risk"]) + _axis_hours(row["complexity"])


def _row_cost(row) -> float:
    return estimate_cost_usd(
        row["scoring_model"] or "",
        input_tokens=row["scoring_input_tokens"] or 0,
        output_tokens=row["scoring_output_tokens"] or 0,
        cache_read=row["scoring_cache_read"] or 0,
        cache_write=row["scoring_cache_write"] or 0,
    ) + estimate_cost_usd(
        row["review_model"] or "",
        input_tokens=row["review_input_tokens"] or 0,
        output_tokens=row["review_output_tokens"] or 0,
        cache_read=row["review_cache_read"] or 0,
        cache_write=row["review_cache_write"] or 0,
    )


# --------------------------------------------------------------------- summary


@dataclass
class Summary:
    group_slug: str | None
    since: int | None
    revisions_seen: int = 0
    revisions_scored: int = 0
    revisions_posted: int = 0
    revisions_skipped: int = 0
    coverage_pct: float = 0.0
    median_risk: float | None = None
    median_complexity: float | None = None
    median_time_to_post_seconds: float | None = None
    estimated_cost_usd: float = 0.0
    time_saved_hours: float = 0.0
    tokens: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_summary(
    rows: Iterable,
    *,
    group_slug: str | None = None,
    since: int | None = None,
) -> Summary:
    seen = 0
    scored = 0
    posted = 0
    skipped = 0
    risks: list[int] = []
    complexities: list[int] = []
    time_to_post: list[int] = []
    tok = defaultdict(int)
    total_cost = 0.0
    total_time_saved = 0.0

    for row in rows:
        if since is not None and (row["seen_at"] or 0) < since:
            continue
        seen += 1
        if row["scored_at"] is not None:
            scored += 1
            if row["risk"] is not None:
                risks.append(row["risk"])
            if row["complexity"] is not None:
                complexities.append(row["complexity"])
        if row["posted"]:
            posted += 1
            if row["posted_at"] and row["revision_created_at"]:
                time_to_post.append(int(row["posted_at"]) - int(row["revision_created_at"]))
        elif row["skipped_reason"]:
            skipped += 1
        for col in (
            "scoring_input_tokens",
            "scoring_output_tokens",
            "scoring_cache_read",
            "scoring_cache_write",
            "review_input_tokens",
            "review_output_tokens",
            "review_cache_read",
            "review_cache_write",
        ):
            tok[col] += row[col] or 0
        total_cost += _row_cost(row)
        total_time_saved += _row_time_saved_hours(row)

    coverage = (posted / seen * 100.0) if seen else 0.0

    return Summary(
        group_slug=group_slug,
        since=since,
        revisions_seen=seen,
        revisions_scored=scored,
        revisions_posted=posted,
        revisions_skipped=skipped,
        coverage_pct=round(coverage, 1),
        median_risk=float(median(risks)) if risks else None,
        median_complexity=float(median(complexities)) if complexities else None,
        median_time_to_post_seconds=float(median(time_to_post)) if time_to_post else None,
        estimated_cost_usd=round(total_cost, 4),
        time_saved_hours=round(total_time_saved, 2),
        tokens=dict(tok),
    )


# --------------------------------------------------------------------- charts


def score_histograms(rows: Iterable) -> dict[str, list[int]]:
    risk_buckets = [0] * 11
    complexity_buckets = [0] * 11
    for row in rows:
        r = row["risk"]
        c = row["complexity"]
        if isinstance(r, int) and 0 <= r <= 10:
            risk_buckets[r] += 1
        if isinstance(c, int) and 0 <= c <= 10:
            complexity_buckets[c] += 1
    return {"risk": risk_buckets, "complexity": complexity_buckets}


def daily_throughput(rows: Iterable, *, days: int = 30) -> list[dict]:
    """Returns [{date: 'YYYY-MM-DD', seen: N, posted: N, cost_usd: N}, ...]"""
    import datetime as dt

    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        seen_at = row["seen_at"]
        if not seen_at:
            continue
        day = dt.datetime.utcfromtimestamp(int(seen_at)).strftime("%Y-%m-%d")
        b = buckets.setdefault(day, {"seen": 0, "posted": 0, "cost_usd": 0.0})
        b["seen"] += 1
        if row["posted"]:
            b["posted"] += 1
        b["cost_usd"] += _row_cost(row)

    out = [
        {"date": d, "seen": v["seen"], "posted": v["posted"], "cost_usd": round(v["cost_usd"], 4)}
        for d, v in sorted(buckets.items())
    ]
    if days:
        out = out[-days:]
    return out


# --------------------------------------------------------------------- detail


def _row_keys(row) -> set[str]:
    """sqlite3.Row supports keys() but other dict-likes used in tests may not."""
    try:
        return set(row.keys())
    except AttributeError:
        return set()


def row_to_detail(row) -> dict:
    """Serialize a single reviewed row for the dashboard / CLI."""
    keys = _row_keys(row)
    findings = []
    if "findings_json" in keys and row["findings_json"]:
        try:
            findings = json.loads(row["findings_json"])
        except json.JSONDecodeError:
            findings = []
    return {
        "revision_phid": row["revision_phid"],
        "revision_id": row["revision_id"],
        "diff_id": row["diff_id"],
        "group_slug": row["group_slug"],
        "title": row["title"],
        "author_phid": row["author_phid"],
        "revision_created_at": row["revision_created_at"],
        "seen_at": row["seen_at"],
        "scored_at": row["scored_at"],
        "risk": row["risk"],
        "complexity": row["complexity"],
        "risk_factors": json.loads(row["risk_factors_json"] or "[]"),
        "complexity_factors": json.loads(row["complexity_factors_json"] or "[]"),
        "scoring_model": row["scoring_model"],
        "review_model": row["review_model"],
        "review_body": row["review_body"],
        "test_files_changed": row["test_files_changed"] if "test_files_changed" in keys else None,
        "non_test_files_changed": (
            row["non_test_files_changed"] if "non_test_files_changed" in keys else None
        ),
        "in_diff_test_signal": (
            row["in_diff_test_signal"] if "in_diff_test_signal" in keys else None
        ),
        "coverage_signal": row["coverage_signal"] if "coverage_signal" in keys else None,
        "inline_count": (row["inline_count"] if "inline_count" in keys else 0) or 0,
        "findings": findings,
        "posted": bool(row["posted"]),
        "posted_at": row["posted_at"],
        "skipped_reason": row["skipped_reason"],
        "final_status": row["final_status"],
        "closed_at": row["closed_at"],
        "human_first_response_at": row["human_first_response_at"],
        "tokens": {
            "scoring": {
                "input": row["scoring_input_tokens"] or 0,
                "output": row["scoring_output_tokens"] or 0,
                "cache_read": row["scoring_cache_read"] or 0,
                "cache_write": row["scoring_cache_write"] or 0,
            },
            "review": {
                "input": row["review_input_tokens"] or 0,
                "output": row["review_output_tokens"] or 0,
                "cache_read": row["review_cache_read"] or 0,
                "cache_write": row["review_cache_write"] or 0,
                "tool_calls": row["review_tool_calls"] or 0,
            },
        },
        "estimated_cost_usd": round(_row_cost(row), 4),
    }
