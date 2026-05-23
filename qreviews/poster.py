"""Render and post the advisory comment to Phabricator."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from qreviews.conduit import ConduitClient
from qreviews.scoring import Scores

log = logging.getLogger(__name__)


COMMENT_TEMPLATE = """\
🤖 **qreviews — automated low-risk advisory review**

This revision was auto-reviewed because its automated **risk** and **complexity** scores were both below the configured threshold of {threshold}.

**Scores**
- Risk: **{risk}/10**
- Complexity: **{complexity}/10**

**Why this looked low-risk**
{risk_bullets}

**Why this looked low-complexity**
{complexity_bullets}

---

{review_body}

---
*Posted by [qreviews]({source_url}) — an unofficial, non-blocking advisory review bot that uses Anthropic's Claude to score risk/complexity and draft low-risk reviews (review model: `{review_model}`). **Advisory only** — it does not accept, reject, or request changes.{dashboard_sentence} Reply with `/qreviews false-positive` to flag a bad call.*
"""

SOURCE_URL = "https://github.com/msujaws/qreviews"


@dataclass
class RenderedComment:
    revision_phid: str
    body: str


def _bulletize(items: list[str]) -> str:
    if not items:
        return "- (no specific factors recorded)"
    return "\n".join(f"- {item.strip()}" for item in items if item.strip())


def render_comment(
    *,
    revision_phid: str,
    scores: Scores,
    review_body: str,
    review_model: str,
    threshold: int,
    dashboard_url: str | None = None,
) -> RenderedComment:
    dashboard_sentence = (
        f" Live metrics & per-revision details: <{dashboard_url}>." if dashboard_url else ""
    )
    body = COMMENT_TEMPLATE.format(
        threshold=threshold,
        risk=scores.risk,
        complexity=scores.complexity,
        risk_bullets=_bulletize(scores.risk_factors),
        complexity_bullets=_bulletize(scores.complexity_factors),
        review_body=review_body.strip(),
        review_model=review_model,
        source_url=SOURCE_URL,
        dashboard_sentence=dashboard_sentence,
    )
    return RenderedComment(revision_phid=revision_phid, body=body)


def post_comment(
    client: ConduitClient,
    *,
    rendered: RenderedComment,
    dry_run: bool = False,
) -> bool:
    """Returns True if posted, False if dry_run was True."""
    if dry_run:
        log.info("dry-run: would post comment to %s (%d chars)", rendered.revision_phid, len(rendered.body))
        return False
    client.post_comment(rendered.revision_phid, rendered.body)
    log.info("posted advisory comment to %s", rendered.revision_phid)
    return True
