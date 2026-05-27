"""Render and post the advisory review to Phabricator.

The bot publishes most findings as inline comments anchored to a
specific (file, line). A single top-level summary comment carries the
scores/factors block, the qreviews footer, any narrative remainder
from the model, and a pointer to the inlines. The summary is always
posted (even when there are zero findings) so the dashboard footer
and "advisory only" framing always appear.
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

Auto-reviewed because risk and complexity scored below the threshold of {threshold}.

**Scores**
- Risk: **{risk}/10**
- Complexity: **{complexity}/10**

**Risk factors**
{risk_bullets}

**Complexity factors**
{complexity_bullets}

---

{findings_section}{review_body_section}
---
*Advisory only — posted by [qreviews]({source_url}) using `{review_model}`. Does not accept, reject, or request changes.{dashboard_sentence} Reply `/qreviews false-positive` to flag a bad call.*
"""

SOURCE_URL = "https://github.com/msujaws/qreviews"


@dataclass
class RenderedComment:
    revision_phid: str
    body: str
    findings: list[Finding] = field(default_factory=list)


def _bulletize(items: list[str]) -> str:
    if not items:
        return "- (no specific factors recorded)"
    return "\n".join(f"- {item.strip()}" for item in items if item.strip())


def _headline(findings_count: int) -> str:
    if findings_count == 0:
        return "no inline findings"
    if findings_count == 1:
        return "1 inline finding on this diff"
    return f"{findings_count} inline findings on this diff"


def _findings_section(findings_count: int) -> str:
    if findings_count == 0:
        return "No inline findings raised at the bot's confidence threshold.\n\n"
    plural = "" if findings_count == 1 else "s"
    return (
        f"Posted {findings_count} inline comment{plural} on this diff — "
        f"see the file view above for line-anchored findings.\n\n"
    )


def render_comment(
    *,
    revision_phid: str,
    scores: Scores,
    review_body: str,
    review_model: str,
    threshold: int,
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
    review_body_section = f"{summary_text}\n\n" if summary_text else ""
    body = COMMENT_TEMPLATE.format(
        headline=_headline(len(findings)),
        threshold=threshold,
        risk=scores.risk,
        complexity=scores.complexity,
        risk_bullets=_bulletize(scores.risk_factors),
        complexity_bullets=_bulletize(scores.complexity_factors),
        findings_section=_findings_section(len(findings)),
        review_body_section=review_body_section,
        review_model=review_model,
        source_url=SOURCE_URL,
        dashboard_sentence=dashboard_sentence,
    )
    return RenderedComment(revision_phid=revision_phid, body=body, findings=findings)


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

    client.publish_review(rendered.revision_phid, rendered.body)
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
    client.publish_review(rendered.revision_phid, rendered.body)
    log.info("posted summary-only comment to %s", rendered.revision_phid)
    return True
