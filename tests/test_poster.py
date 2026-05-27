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
    # Footer references the service and links to the source on GitHub.
    assert "qreviews" in out.body
    assert SOURCE_URL in out.body
    assert "advisory only" in out.body.lower()
    # Style-guide invariants: no emoji in the wrapper, and the factor
    # sections use neutral Mozilla-bug-style labels.
    assert "🤖" not in out.body
    assert "Risk factors" in out.body
    assert "Complexity factors" in out.body


def test_render_includes_deep_link_when_url_and_revision_id_provided():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="ok",
        review_model="claude-sonnet-4-6",
        threshold=2,
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
        threshold=2,
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
        threshold=2,
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
        threshold=2,
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
        threshold=2,
    )
    assert "no inline findings" in no_findings.body.lower()

    one = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        threshold=2,
        findings=[_finding()],
    )
    assert "1 inline finding" in one.body

    two = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        threshold=2,
        findings=[_finding(), _finding(line=20)],
    )
    assert "2 inline findings" in two.body


def test_render_attaches_findings_for_posting():
    out = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        threshold=2,
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
        threshold=2,
        findings=[_finding(), _finding(path="b.cpp", line=42)],
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
    # Summary published last.
    client.publish_review.assert_called_once()
    _, kwargs = client.publish_review.call_args
    # publish_review is called positionally — verify args order.
    pos_args = client.publish_review.call_args.args
    assert pos_args[0] == "PHID-DREV-1"
    assert "qreviews" in pos_args[1]


def test_post_review_dry_run_emits_no_calls():
    client = MagicMock()
    rendered = render_comment(
        revision_phid="PHID-DREV-1",
        scores=_scores(),
        review_body="",
        review_model="m",
        threshold=2,
        findings=[_finding()],
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
        threshold=2,
        findings=[_finding(), _finding(path="b.cpp", line=42)],
    )
    posted = post_review(client, rendered=rendered, diff_id=1)
    # First inline failed, second succeeded; summary still published.
    assert posted == 1
    client.publish_review.assert_called_once()
