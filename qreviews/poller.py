"""Polling loop: discover → score → maybe-review → post → record.

Designed so `process_revision()` is reusable by the webhook receiver later.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

from qreviews.conduit import ConduitClient, Revision
from qreviews.config import Config, ReviewerGroup, Secrets
from qreviews.poster import post_comment, render_comment
from qreviews.review import generate_review
from qreviews.scoring import score_revision
from qreviews.skills import discover_skill_dirs
from qreviews.state import Store

log = logging.getLogger(__name__)


# Phabricator status values that mean "author isn't asking for a review
# right now." `draft` is the pre-request state; `changes-planned` is what
# Phabricator's "Plan Changes" button sets when the author wants to take
# the revision back to WIP. Polling filters to `needs-review` already, so
# these only reach us via the Herald webhook, but `process_revision()` is
# the chokepoint for both paths.
NOT_READY_FOR_REVIEW_STATUSES = frozenset({"draft", "changes-planned"})


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
        self._supplemental_skills: dict[str, Path] = {}
        self._supplemental_ready = False
        self._group_member_phids: dict[str, set[str]] = {}
        # Secure-revision PHID is resolved lazily on first process_revision
        # call. None after resolve = misconfigured slug or transient failure;
        # we memoize the miss so we don't hammer project.search every poll.
        self._secure_revision_phid: str | None = None
        self._secure_revision_resolved = False

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

    def resolve_group_members(self, slug: str, group_phid: str) -> set[str]:
        """Return the set of user PHIDs that are members of the group's project.

        Cached in memory for the lifetime of the Poller; a process restart
        re-fetches and picks up membership changes.
        """
        if slug in self._group_member_phids:
            return self._group_member_phids[slug]
        members = self.conduit.project_members(group_phid)
        self._group_member_phids[slug] = members
        log.info("resolved %d member(s) for group %s", len(members), slug)
        return members

    # ------------------------------------------------------------ supplemental skills

    def _skills_root(self) -> Path:
        """`skills/` directory at the repo root, located relative to this file."""
        return Path(__file__).resolve().parent.parent / "skills"

    def _ensure_supplemental_skills(self) -> dict[str, Path]:
        """Lazily discover supplemental skills and resolve them to PHIDs.

        Builds (and caches) `self._supplemental_skills`, a `phid → SKILL.md
        path` map. Slugs that fail to resolve in Phabricator are dropped
        silently. Called on first use so test setups that never poll don't
        pay the network cost.
        """
        if self._supplemental_ready:
            return self._supplemental_skills
        self._supplemental_ready = True
        discovered = discover_skill_dirs(self._skills_root())
        if not discovered:
            return self._supplemental_skills
        # Use cached PHIDs where possible to avoid a Conduit call per process.
        unresolved: list[str] = []
        slug_to_phid: dict[str, str] = {}
        for slug in discovered:
            phid = self._group_phids.get(slug) or self.store.get_cached_phid(slug)
            if phid:
                slug_to_phid[slug] = phid
            else:
                unresolved.append(slug)
        if unresolved:
            try:
                resolved = self.conduit.resolve_project_phids(unresolved)
            except Exception:
                log.exception("supplemental skill PHID resolution failed")
                resolved = {}
            for slug, phid in resolved.items():
                self.store.cache_phid(slug, phid)
                slug_to_phid[slug] = phid
            for slug in unresolved:
                if slug not in resolved:
                    log.debug("supplemental skill slug not resolved in Phabricator: %s", slug)
        for slug, phid in slug_to_phid.items():
            self._group_phids.setdefault(slug, phid)
            self._supplemental_skills[phid] = discovered[slug]
        log.info(
            "supplemental skills ready: %d resolved out of %d discovered",
            len(self._supplemental_skills),
            len(discovered),
        )
        return self._supplemental_skills

    def additional_skill_paths_for(
        self, revision: Revision, *, primary_phid: str
    ) -> list[str]:
        """Skill paths to attach as supplemental context for this revision.

        Excludes the primary group's own PHID so its skill isn't loaded
        twice. Result is sorted by path for deterministic prompt ordering.
        """
        skills = self._ensure_supplemental_skills()
        if not skills:
            return []
        paths: list[str] = []
        for phid in revision.reviewer_phids:
            if phid == primary_phid:
                continue
            path = skills.get(phid)
            if path is not None:
                paths.append(str(path))
        paths.sort()
        return paths

    def resolve_secure_revision_phid(self) -> str | None:
        """PHID of Mozilla's `secure-revision` project tag, or None if it
        can't be resolved.

        Cached for the lifetime of the Poller (and across restarts via
        Store.get_cached_phid). A failed resolve is logged once and
        memoized as a miss so we don't hammer project.search every poll.
        """
        if self._secure_revision_resolved:
            return self._secure_revision_phid
        slug = self.config.phabricator.secure_revision_project_slug
        cached = self.store.get_cached_phid(slug)
        if cached:
            self._secure_revision_phid = cached
            self._secure_revision_resolved = True
            return cached
        try:
            phid = self.conduit.resolve_project_phid(slug)
        except Exception:
            log.exception("failed to resolve secure-revision PHID (slug=%s)", slug)
            self._secure_revision_resolved = True
            return None
        if not phid:
            log.warning(
                "secure-revision project slug %r did not resolve; "
                "security-sensitive revisions will NOT be skipped until "
                "this is fixed",
                slug,
            )
            self._secure_revision_resolved = True
            return None
        self.store.cache_phid(slug, phid)
        self._secure_revision_phid = phid
        self._secure_revision_resolved = True
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

        if revision.status in NOT_READY_FOR_REVIEW_STATUSES:
            log.info(
                "skipping %s: status=%s (author has not requested review)",
                revision.display_id,
                revision.status,
            )
            return ProcessResult(
                revision_id=revision.id,
                posted=False,
                skipped_reason=f"status_{revision.status.replace('-', '_')}",
            )

        # Security-sensitive revisions (Mozilla's `secure-revision` project
        # tag) must never reach scoring or review. Bail before fetching the
        # diff so we don't even pull restricted content into memory.
        secure_phid = self.resolve_secure_revision_phid()
        if secure_phid and secure_phid in revision.project_phids:
            log.info("skipping %s: tagged secure-revision", revision.display_id)
            return ProcessResult(
                revision_id=revision.id,
                posted=False,
                skipped_reason="security_sensitive",
            )

        # Author-membership gate: while qreviews is being validated, only
        # review revisions whose author is in the group's Phabricator project.
        # If the members lookup returns empty (transient failure, etc.) we
        # don't skip — we'd rather over-include than silently drop everything.
        if group.restrict_to_member_authors:
            group_phid = self.resolve_group_phid(group.slug)
            members = self.resolve_group_members(group.slug, group_phid)
            if members and revision.author_phid not in members:
                log.info(
                    "skipping %s: author %s is not a member of %s",
                    revision.display_id,
                    revision.author_phid,
                    group.slug,
                )
                return ProcessResult(
                    revision_id=revision.id,
                    posted=False,
                    skipped_reason="author_not_in_group",
                )

        diff = self.conduit.latest_diff(revision.phid)
        if not diff:
            log.warning("no diff found for %s", revision.display_id)
            return ProcessResult(revision_id=revision.id, posted=False, skipped_reason="no_diff")

        # Dedup: have we already handled this revision/diff combo?
        if self.store.already_reviewed(revision.phid, diff.phid):
            log.debug("already processed %s diff %s", revision.display_id, diff.id)
            return ProcessResult(revision_id=revision.id, posted=False, skipped_reason="dedup")

        # One review per revision: if we've already posted on any diff of this
        # revision, don't review again even when the author pushes a new diff.
        if self.store.already_posted_on_revision(revision.phid):
            log.info(
                "skipping %s: qreviews already commented on a prior diff",
                revision.display_id,
            )
            return ProcessResult(
                revision_id=revision.id,
                posted=False,
                skipped_reason="already_reviewed_by_qreviews",
            )

        # Engagement signal: if a non-author human has commented on the
        # revision, a reviewer is already paying attention — stay out of the
        # way. Application-issued transactions (Herald, etc.) are filtered.
        human_commenters = self.conduit.human_commenter_phids(
            revision.id,
            author_phid=revision.author_phid,
            ignore_phids=set(self.config.phabricator.ignore_commenter_phids),
        )
        if human_commenters:
            log.info(
                "skipping %s: already commented on by %d non-author user(s)",
                revision.display_id,
                len(human_commenters),
            )
            return ProcessResult(
                revision_id=revision.id,
                posted=False,
                skipped_reason="already_commented",
            )

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

        # Pull in extra reviewer-group skills if the revision is tagged
        # with groups beyond the one we matched on.
        try:
            primary_phid = self.resolve_group_phid(group.slug)
        except Exception:
            primary_phid = ""
        additional_skill_paths = self.additional_skill_paths_for(
            revision, primary_phid=primary_phid
        )
        if additional_skill_paths:
            log.info(
                "%s: attaching %d supplemental skill(s): %s",
                revision.display_id,
                len(additional_skill_paths),
                ", ".join(Path(p).parent.name for p in additional_skill_paths),
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
                additional_skill_paths=additional_skill_paths,
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
