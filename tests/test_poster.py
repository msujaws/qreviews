"""Comment rendering."""

from __future__ import annotations

from qreviews.poster import render_comment
from qreviews.scoring import Scores


def test_render_includes_scores_and_factors():
    scores = Scores(
        risk=1,
        complexity=0,
        risk_factors=["touches only browser/components/newtab/styles.css"],
        complexity_factors=["3 LOC added, no logic change"],
    )
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=scores,
        review_body="### Looks good\n\nNo findings.",
        review_model="claude-sonnet-4-6",
        threshold=2,
    )
    assert "Risk: **1/10**" in out.body
    assert "Complexity: **0/10**" in out.body
    assert "browser/components/newtab/styles.css" in out.body
    assert "3 LOC added" in out.body
    assert "No findings." in out.body
    assert "advisory only" in out.body.lower()
