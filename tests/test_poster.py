"""Comment rendering."""

from __future__ import annotations

from qreviews.poster import SOURCE_URL, render_comment
from qreviews.scoring import Scores


def _scores() -> Scores:
    return Scores(
        risk=1,
        complexity=0,
        risk_factors=["touches only browser/components/newtab/styles.css"],
        complexity_factors=["3 LOC added, no logic change"],
    )


def test_render_includes_scores_and_factors():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="### Looks good\n\nNo findings.",
        review_model="claude-sonnet-4-6",
        threshold=2,
    )
    assert "Risk: **1/10**" in out.body
    assert "Complexity: **0/10**" in out.body
    assert "browser/components/newtab/styles.css" in out.body
    assert "3 LOC added" in out.body
    assert "No findings." in out.body
    # New footer: names the service and links to the source on GitHub.
    assert "qreviews" in out.body
    assert SOURCE_URL in out.body
    assert "advisory only" in out.body.lower()


def test_render_includes_dashboard_url_when_provided():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="ok",
        review_model="claude-sonnet-4-6",
        threshold=2,
        dashboard_url="https://qreviews.example",
    )
    assert "https://qreviews.example" in out.body
    assert "Live metrics" in out.body


def test_render_omits_dashboard_sentence_when_url_unset():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="ok",
        review_model="claude-sonnet-4-6",
        threshold=2,
        dashboard_url=None,
    )
    # No dangling sentence or empty URL placeholder when unconfigured.
    assert "Live metrics" not in out.body
    assert "<>" not in out.body
    assert "None" not in out.body
