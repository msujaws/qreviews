"""Comment rendering + inline-posting orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

from qreviews.poster import SOURCE_URL, post_review, render_comment
from qreviews.review import Finding
from qreviews.scoring import Scores


def _scores() -> Scores:
    return Scores(
        risk=1,
        complexity=0,
        risk_factors=["touches only browser/components/newtab/styles.css"],
        complexity_factors=["3 LOC added, no logic change"],
    )


def _finding(path: str = "browser/components/newtab/Foo.jsx", line: int = 10) -> Finding:
    return Finding(file_path=path, line=line, is_new_file=True, body="Fix the thing.")


def test_render_collapses_scores_to_one_sentence():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="This commit lacks a corresponding test file.",
        review_model="claude-sonnet-4-6",
        risk_threshold=2,
        complexity_threshold=2,
    )
    assert "Risk 1/10, complexity 0/10." in out.body
    assert "Below the auto-review threshold of 2." in out.body
    assert "This commit lacks a corresponding test file." in out.body
    # Footer references the service and links to the source on GitHub.
    assert "qreviews" in out.body
    assert SOURCE_URL in out.body
    assert "advisory only" in out.body.lower()
    # Style-guide invariants: no emoji, and no middot separator.
    assert "🤖" not in out.body
    assert "·" not in out.body


def test_render_omits_score_factors():
    # Factors live in the DB and the dashboard drawer, not in the comment —
    # ten bullets of bot rationale ahead of anything actionable.
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="claude-sonnet-4-6",
        risk_threshold=2,
        complexity_threshold=2,
    )
    assert "browser/components/newtab/styles.css" not in out.body
    assert "3 LOC added" not in out.body
    assert "Risk factors" not in out.body
    assert "Complexity factors" not in out.body


def test_render_body_stays_short():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="claude-sonnet-4-6",
        risk_threshold=2,
        complexity_threshold=2,
        dashboard_url="https://qreviews.example",
        revision_id=12345,
    )
    assert len(out.body.splitlines()) <= 8


def test_render_names_both_thresholds_when_they_differ():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="claude-sonnet-4-6",
        risk_threshold=4,
        complexity_threshold=3,
    )
    assert "Below the auto-review thresholds of 4 risk and 3 complexity." in out.body


def test_render_includes_deep_link_when_url_and_revision_id_provided():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="ok",
        review_model="claude-sonnet-4-6",
        risk_threshold=2,
        complexity_threshold=2,
        dashboard_url="https://qreviews.example",
        revision_id=12345,
    )
    assert "https://qreviews.example/?rev=D12345" in out.body
    assert "View this revision" in out.body


def test_render_deep_link_strips_trailing_slash_on_base_url():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="ok",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        dashboard_url="https://qreviews.example/",
        revision_id=7,
    )
    assert "https://qreviews.example/?rev=D7" in out.body
    assert "https://qreviews.example//?rev=" not in out.body


def test_render_falls_back_when_revision_id_missing():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="ok",
        review_model="claude-sonnet-4-6",
        risk_threshold=2,
        complexity_threshold=2,
        dashboard_url="https://qreviews.example",
        revision_id=None,
    )
    assert "https://qreviews.example" in out.body
    assert "Live metrics" in out.body
    assert "?rev=" not in out.body


def test_render_omits_dashboard_sentence_when_url_unset():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="ok",
        review_model="claude-sonnet-4-6",
        risk_threshold=2,
        complexity_threshold=2,
        dashboard_url=None,
        revision_id=12345,
    )
    # No dangling sentence or empty URL placeholder when unconfigured.
    assert "Live metrics" not in out.body
    assert "View this revision" not in out.body
    assert "<>" not in out.body
    assert "None" not in out.body


def test_render_headline_reflects_findings_count():
    no_findings = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
    )
    assert "no inline findings" in no_findings.body.lower()

    one = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        findings=[_finding()],
    )
    assert "1 inline finding" in one.body

    two = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        findings=[_finding(), _finding(line=20)],
    )
    assert "2 inline findings" in two.body


def test_render_attaches_findings_for_posting():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        findings=[_finding()],
    )
    assert len(out.findings) == 1


def test_post_review_creates_inlines_then_publishes():
    client = MagicMock()
    rendered = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        findings=[_finding(), _finding(path="b.cpp", line=42)],
        revision_id=302879,
    )
    posted = post_review(client, rendered=rendered, diff_id=99)
    assert posted == 2
    # Two inlines created with the right anchors.
    assert client.create_inline.call_count == 2
    first_call = client.create_inline.call_args_list[0]
    assert first_call.kwargs["diff_id"] == 99
    assert first_call.kwargs["file_path"] == "browser/components/newtab/Foo.jsx"
    assert first_call.kwargs["line"] == 10
    assert first_call.kwargs["is_new_file"] is True
    # Summary published last via createcomment+attach_inlines, identified
    # by the numeric revision id (not the PHID).
    client.publish_review.assert_called_once()
    pos_args = client.publish_review.call_args.args
    assert pos_args[0] == 302879
    assert "qreviews" in pos_args[1]


def test_post_review_dry_run_emits_no_calls():
    client = MagicMock()
    rendered = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        findings=[_finding()],
        revision_id=302879,
    )
    posted = post_review(client, rendered=rendered, diff_id=99, dry_run=True)
    assert posted == 0
    client.create_inline.assert_not_called()
    client.publish_review.assert_not_called()


def test_post_review_continues_past_inline_errors():
    client = MagicMock()
    client.create_inline.side_effect = [RuntimeError("conduit blew up"), "PHID-XCMT-ok"]
    rendered = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        findings=[_finding(), _finding(path="b.cpp", line=42)],
        revision_id=302879,
    )
    posted = post_review(client, rendered=rendered, diff_id=1)
    # First inline failed, second succeeded; summary still published.
    assert posted == 1
    client.publish_review.assert_called_once()


def test_post_review_skips_publish_when_revision_id_missing():
    client = MagicMock()
    rendered = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        risk_threshold=2,
        complexity_threshold=2,
        findings=[_finding()],
    )
    posted = post_review(client, rendered=rendered, diff_id=99)
    # Without a revision_id we can't call differential.createcomment;
    # surface the failure rather than silently skipping inlines.
    assert posted == 0
    client.create_inline.assert_not_called()
    client.publish_review.assert_not_called()
