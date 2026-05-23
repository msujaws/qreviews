"""Polling loop: discover → score → maybe-review → post → record.

Designed so `process_revision()` is reusable by the webhook receiver later.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from anthropic import Anthropic

from qreviews.conduit import ConduitClient, Revision
from qreviews.config import Config, ReviewerGroup, Secrets
from qreviews.poster import post_comment, render_comment
from qreviews.review import generate_review
from qreviews.scoring import score_revision
from qreviews.state import Store

log = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    revision_id: int
    posted: bool
    skipped_reason: str | None = None
    risk: int | None = None
    complexity: int | None = None


class Poller:
    def __init__(
        self,
        config: Config,
        secrets: Secrets,
        store: Store,
        conduit: ConduitClient | None = None,
        anthropic_client: Anthropic | None = None,
    ):
        self.config = config
        self.secrets = secrets
        self.store = store
        self.conduit = conduit or ConduitClient(
            base_url=config.phabricator.base_url,
            api_token=secrets.phabricator_api_token,
            user_agent=config.phabricator.user_agent,
        )
        self.anthropic = anthropic_client or Anthropic(api_key=secrets.anthropic_api_key)
        self._group_phids: dict[str, str] = {}

    # ------------------------------------------------------------ phid resolve

    def resolve_group_phid(self, slug: str) -> str:
        if slug in self._group_phids:
            return self._group_phids[slug]
        cached = self.store.get_cached_phid(slug)
        if cached:
            self._group_phids[slug] = cached
            return cached
        phid = self.conduit.resolve_project_phid(slug)
        if not phid:
            raise RuntimeError(f"could not resolve PHID for reviewer group: {slug}")
        self.store.cache_phid(slug, phid)
        self._group_phids[slug] = phid
        log.info("resolved %s → %s", slug, phid)
        return phid

    # ------------------------------------------------------------ per-revision

    def process_revision(
        self,
        revision: Revision,
        group: ReviewerGroup,
        *,
        dry_run: bool = False,
    ) -> ProcessResult:
        if revision.status == "accepted":
            log.info("skipping %s: already accepted by a human reviewer", revision.display_id)
            return ProcessResult(
                revision_id=revision.id,
                posted=False,
                skipped_reason="already_accepted",
            )

        diff = self.conduit.latest_diff(revision.phid)
        if not diff:
            log.warning("no diff found for %s", revision.display_id)
            return ProcessResult(revision_id=revision.id, posted=False, skipped_reason="no_diff")

        # Dedup: have we already handled this revision/diff combo?
        if self.store.already_reviewed(revision.phid, diff.phid):
            log.debug("already processed %s diff %s", revision.display_id, diff.id)
            return ProcessResult(revision_id=revision.id, posted=False, skipped_reason="dedup")

        self.store.record_seen(
            revision_phid=revision.phid,
            diff_phid=diff.phid,
            diff_id=diff.id,
            revision_id=revision.id,
            group_slug=group.slug,
            title=revision.title,
            author_phid=revision.author_phid,
            revision_created_at=revision.date_created,
        )

        raw_diff = self.conduit.get_raw_diff(diff.id)
        if len(raw_diff.encode("utf-8")) > self.config.phabricator.max_diff_bytes:
            log.info("skipping %s: diff too large", revision.display_id)
            self.store.record_skipped(
                revision_phid=revision.phid,
                diff_phid=diff.phid,
                reason="oversized_diff",
            )
            return ProcessResult(
                revision_id=revision.id, posted=False, skipped_reason="oversized_diff"
            )

        # Score
        try:
            scoring = score_revision(
                self.anthropic,
                model=self.config.anthropic.scoring_model,
                max_tokens=self.config.anthropic.scoring_max_tokens,
                title=revision.title,
                summary=revision.summary,
                revision_id=revision.id,
                author_phid=revision.author_phid,
                bug_id=revision.bug_id,
                raw_diff=raw_diff,
            )
        except Exception as e:
            log.exception("scoring failed for %s: %s", revision.display_id, e)
            self.store.record_skipped(
                revision_phid=revision.phid,
                diff_phid=diff.phid,
                reason="scoring_error",
            )
            return ProcessResult(
                revision_id=revision.id, posted=False, skipped_reason="scoring_error"
            )

        self.store.record_scored(
            revision_phid=revision.phid,
            diff_phid=diff.phid,
            risk=scoring.scores.risk,
            complexity=scoring.scores.complexity,
            risk_factors=scoring.scores.risk_factors,
            complexity_factors=scoring.scores.complexity_factors,
            model=scoring.model,
            usage=scoring.usage,
        )

        risk_threshold = group.effective_risk_threshold(self.config.defaults)
        complexity_threshold = group.effective_complexity_threshold(self.config.defaults)
        log.info(
            "%s scored risk=%d complexity=%d (group thresholds <%d/%d)",
            revision.display_id,
            scoring.scores.risk,
            scoring.scores.complexity,
            risk_threshold,
            complexity_threshold,
        )

        if (
            scoring.scores.risk >= risk_threshold
            or scoring.scores.complexity >= complexity_threshold
        ):
            self.store.record_reviewed(
                revision_phid=revision.phid,
                diff_phid=diff.phid,
                review_body="",
                model="",
                usage={},
                posted=False,
                skipped_reason="above_threshold",
            )
            return ProcessResult(
                revision_id=revision.id,
                posted=False,
                skipped_reason="above_threshold",
                risk=scoring.scores.risk,
                complexity=scoring.scores.complexity,
            )

        if not group.skill_path:
            log.warning("group %s passed threshold but has no skill_path", group.slug)
            self.store.record_reviewed(
                revision_phid=revision.phid,
                diff_phid=diff.phid,
                review_body="",
                model="",
                usage={},
                posted=False,
                skipped_reason="no_skill_configured",
            )
            return ProcessResult(
                revision_id=revision.id,
                posted=False,
                skipped_reason="no_skill_configured",
                risk=scoring.scores.risk,
                complexity=scoring.scores.complexity,
            )

        # Generate review
        try:
            review = generate_review(
                self.anthropic,
                model=self.config.anthropic.review_model,
                max_tokens=self.config.anthropic.review_max_tokens,
                skill_path=group.skill_path,
                title=revision.title,
                summary=revision.summary,
                revision_id=revision.id,
                author_phid=revision.author_phid,
                bug_id=revision.bug_id,
                raw_diff=raw_diff,
            )
        except Exception as e:
            log.exception("review generation failed for %s: %s", revision.display_id, e)
            self.store.record_reviewed(
                revision_phid=revision.phid,
                diff_phid=diff.phid,
                review_body="",
                model="",
                usage={},
                posted=False,
                skipped_reason="review_error",
            )
            return ProcessResult(
                revision_id=revision.id, posted=False, skipped_reason="review_error"
            )

        rendered = render_comment(
            revision_phid=revision.phid,
            scores=scoring.scores,
            review_body=review.body,
            review_model=review.model,
            threshold=max(risk_threshold, complexity_threshold),
            dashboard_url=self.config.dashboard.public_url,
        )

        posted = post_comment(self.conduit, rendered=rendered, dry_run=dry_run)

        self.store.record_reviewed(
            revision_phid=revision.phid,
            diff_phid=diff.phid,
            review_body=rendered.body,
            model=review.model,
            usage=review.usage,
            posted=posted,
            skipped_reason=None if posted else "dry_run",
            tool_calls=review.tool_calls,
        )

        return ProcessResult(
            revision_id=revision.id,
            posted=posted,
            risk=scoring.scores.risk,
            complexity=scoring.scores.complexity,
        )

    # ------------------------------------------------------------ per-group

    def poll_group(self, group: ReviewerGroup, *, dry_run: bool = False) -> list[ProcessResult]:
        if not group.enabled:
            return []
        phid = self.resolve_group_phid(group.slug)

        last = self.store.get_watermark(group.slug)
        overlap = self.config.phabricator.watermark_overlap_seconds
        modified_since = (last - overlap) if last else (int(time.time()) - 86400)

        revisions = self.conduit.search_revisions(
            reviewer_phids=[phid],
            statuses=("needs-review",),
            modified_since=modified_since,
        )
        log.info(
            "group %s: %d revisions modified since %d",
            group.slug,
            len(revisions),
            modified_since,
        )

        results: list[ProcessResult] = []
        for rev in revisions:
            try:
                results.append(self.process_revision(rev, group, dry_run=dry_run))
            except Exception:
                log.exception("error processing %s", rev.display_id)

        # Advance watermark to the most recent modification we observed (or now).
        if revisions:
            new_watermark = max(r.date_modified for r in revisions)
            self.store.set_watermark(group.slug, new_watermark)

        return results

    # ------------------------------------------------------------ backfill

    def backfill_status(self) -> int:
        """Refresh final_status / human_first_response_at for previously seen rows."""
        rows = self.store.revisions_to_backfill(batch=50)
        if not rows:
            return 0
        phids = [r["revision_phid"] for r in rows]
        try:
            revs = self.conduit.search_revisions_by_phids(phids)
        except Exception:
            log.exception("backfill: search_revisions_by_phids failed")
            return 0
        # human_first_response_at — left null for v0; populated once we add
        # a `transaction.search` pass. We refresh the lighter signals now.
        for r in revs:
            self.store.update_final_status(
                r.phid,
                final_status=r.status,
                closed_at=r.date_modified if r.status in ("published", "abandoned") else None,
                human_first_response_at=None,
            )
        return len(revs)

    # ------------------------------------------------------------ loop

    def run_forever(self, *, dry_run: bool = False) -> None:
        interval = self.config.phabricator.poll_interval_seconds
        log.info("starting poll loop (interval=%ds, dry_run=%s)", interval, dry_run)
        while True:
            for group in self.config.enabled_groups():
                try:
                    self.poll_group(group, dry_run=dry_run)
                except Exception:
                    log.exception("error polling group %s", group.slug)
            try:
                self.backfill_status()
            except Exception:
                log.exception("backfill_status failed")
            time.sleep(interval)
