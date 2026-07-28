"""Render and post the advisory review to Phabricator.

The bot publishes most findings as inline comments anchored to a
specific (file, line). A single top-level summary comment carries one
sentence of scores, a pointer to the inlines, any narrative remainder
from the model, and the qreviews footer. The summary is always posted
(even when there are zero findings) so the dashboard footer and
"advisory only" framing always appear.

The scores line is deliberately terse. Per-axis risk and complexity
factors used to be bulleted here — up to ten bullets ahead of anything
actionable. They are still recorded in `qreviews/state.py` and rendered
in the dashboard's revision drawer, which the footer deep-links to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from qreviews.conduit import ConduitClient
from qreviews.review import Finding
from qreviews.scoring import Scores

log = logging.getLogger(__name__)


COMMENT_TEMPLATE = """\
**qreviews — {headline}**

{score_sentence} {threshold_sentence} {findings_sentence}
{review_body_section}
---
*Advisory only — posted by [qreviews]({source_url}) using `{review_model}`. Does not accept, reject, or request changes.{dashboard_sentence}*
"""

SOURCE_URL = "https://github.com/msujaws/qreviews"


@dataclass
class RenderedComment:
    revision_phid: str
    body: str
    findings: list[Finding] = field(default_factory=list)
    revision_id: int | None = None


def _headline(findings_count: int) -> str:
    if findings_count == 0:
        return "no inline findings"
    if findings_count == 1:
        return "1 inline finding on this diff"
    return f"{findings_count} inline findings on this diff"


def _score_sentence(scores: Scores) -> str:
    return f"Risk {scores.risk}/10, complexity {scores.complexity}/10."


def _threshold_sentence(risk_threshold: int, complexity_threshold: int) -> str:
    if risk_threshold == complexity_threshold:
        return f"Below the auto-review threshold of {risk_threshold}."
    return (
        f"Below the auto-review thresholds of {risk_threshold} risk and "
        f"{complexity_threshold} complexity."
    )


def _findings_sentence(findings_count: int) -> str:
    if findings_count == 0:
        return "No inline findings raised at the confidence threshold."
    plural = "" if findings_count == 1 else "s"
    return f"Posted {findings_count} inline comment{plural} on this diff."


def render_comment(
    *,
    revision_phid: str,
    scores: Scores,
    review_body: str,
    review_model: str,
    risk_threshold: int,
    complexity_threshold: int,
    findings: list[Finding] | None = None,
    dashboard_url: str | None = None,
    revision_id: int | None = None,
) -> RenderedComment:
    findings = list(findings or [])
    if dashboard_url and revision_id is not None:
        deep_url = f"{dashboard_url.rstrip('/')}/?rev=D{revision_id}"
        dashboard_sentence = f" View this revision on the dashboard: <{deep_url}>."
    elif dashboard_url:
        dashboard_sentence = f" Live metrics & per-revision details: <{dashboard_url}>."
    else:
        dashboard_sentence = ""
    summary_text = review_body.strip()
    review_body_section = f"\n{summary_text}\n" if summary_text else ""
    body = COMMENT_TEMPLATE.format(
        headline=_headline(len(findings)),
        score_sentence=_score_sentence(scores),
        threshold_sentence=_threshold_sentence(risk_threshold, complexity_threshold),
        findings_sentence=_findings_sentence(len(findings)),
        review_body_section=review_body_section,
        review_model=review_model,
        source_url=SOURCE_URL,
        dashboard_sentence=dashboard_sentence,
    )
    return RenderedComment(
        revision_phid=revision_phid,
        body=body,
        findings=findings,
        revision_id=revision_id,
    )


def post_review(
    client: ConduitClient,
    *,
    rendered: RenderedComment,
    diff_id: int,
    dry_run: bool = False,
) -> int:
    """Post inline findings then the summary comment. Returns the number of
    inlines successfully created. On dry_run, logs intent and returns 0.
    """
    if dry_run:
        log.info(
            "dry-run: would post %d inline finding(s) + summary to %s",
            len(rendered.findings),
            rendered.revision_phid,
        )
        return 0

    if rendered.revision_id is None:
        log.error(
            "post_review: rendered comment for %s has no revision_id; "
            "cannot publish via differential.createcomment",
            rendered.revision_phid,
        )
        return 0

    posted_inlines = 0
    for finding in rendered.findings:
        try:
            client.create_inline(
                diff_id=diff_id,
                file_path=finding.file_path,
                line=finding.line,
                is_new_file=finding.is_new_file,
                content=finding.body,
            )
            posted_inlines += 1
        except Exception:
            log.exception(
                "failed to create inline at %s:%d on %s",
                finding.file_path,
                finding.line,
                rendered.revision_phid,
            )
            # Keep going — one bad inline shouldn't drop the rest.

    client.publish_review(rendered.revision_id, rendered.body)
    log.info(
        "posted review to %s: %d inline finding(s), %d char summary",
        rendered.revision_phid,
        posted_inlines,
        len(rendered.body),
    )
    return posted_inlines


def post_comment(
    client: ConduitClient,
    *,
    rendered: RenderedComment,
    dry_run: bool = False,
) -> bool:
    """Backwards-compatible shim: post the summary only, no inlines.

    Kept for callers that don't have a diff_id handy. New code should
    prefer `post_review` so inline findings get posted alongside the
    summary.
    """
    if dry_run:
        log.info(
            "dry-run: would post summary-only comment to %s (%d chars)",
            rendered.revision_phid,
            len(rendered.body),
        )
        return False
    if rendered.revision_id is None:
        log.error(
            "post_comment: rendered comment for %s has no revision_id; "
            "cannot publish via differential.createcomment",
            rendered.revision_phid,
        )
        return False
    client.publish_review(rendered.revision_id, rendered.body)
    log.info("posted summary-only comment to %s", rendered.revision_phid)
    return True
