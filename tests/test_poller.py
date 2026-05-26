"""Poller — end-to-end with mocked Conduit + Anthropic."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qreviews.conduit import Diff, Revision
from qreviews.poller import Poller


def _rev(
    revision_id: int = 100,
    project_phids: list[str] | None = None,
    status: str = "needs-review",
) -> Revision:
    return Revision(
        phid=f"PHID-DREV-{revision_id}",
        id=revision_id,
        title="Fix the thing",
        summary="It was broken.",
        status=status,
        author_phid="PHID-USER-1",
        repository_phid="PHID-REPO-1",
        bug_id="9999",
        date_created=1716000000,
        date_modified=1716000100,
        reviewer_phids=["PHID-PROJ-ip"],
        project_phids=project_phids or [],
    )


def _diff(diff_id: int = 1, revision_phid: str = "PHID-DREV-100") -> Diff:
    return Diff(phid=f"PHID-DIFF-{diff_id}", id=diff_id, revision_phid=revision_phid, date_created=1)


def _claude_text(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0
        ),
    )


@pytest.fixture
def mocked_poller(config, store, tmp_path):
    config.reviewer_groups[0].skill_path = str(tmp_path / "fake_skill.md")
    (tmp_path / "fake_skill.md").write_text("# Fake skill\nRules: be nice.")

    conduit = MagicMock()
    conduit.latest_diff.return_value = _diff()
    conduit.get_raw_diff.return_value = "@@ -1 +1 @@\n-old\n+new\n"
    conduit.resolve_project_phid.return_value = "PHID-PROJ-ip"
    conduit.search_revisions.return_value = [_rev()]
    conduit.search_revisions_by_phids.return_value = []
    conduit.post_comment.return_value = {"object": {"id": 100}}
    # Default: no human commenters — set explicitly so MagicMock's truthy
    # default doesn't accidentally trip the "already_commented" skip.
    conduit.human_commenter_phids.return_value = set()
    # Default: the test author is a member of the group, so the
    # restrict_to_member_authors gate lets revisions through.
    conduit.project_members.return_value = {"PHID-USER-1"}

    anthropic = MagicMock()

    secrets = SimpleNamespace(phabricator_api_token="api-x", anthropic_api_key="sk-ant-x")
    return Poller(config, secrets, store, conduit=conduit, anthropic_client=anthropic), conduit, anthropic


def test_process_revision_below_threshold_posts(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    anthropic.messages.create.side_effect = [
        _claude_text(json.dumps({
            "risk": 1, "complexity": 1,
            "risk_factors": ["docs only"], "complexity_factors": ["3 LOC"],
        })),
        _claude_text("### Looks good\nNo findings — straightforward docs change."),
    ]
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(_rev(), group, dry_run=False)
    assert result.posted is True
    assert result.risk == 1
    assert result.complexity == 1
    conduit.post_comment.assert_called_once()
    # The posted body should include the score scaffold + the Claude review body.
    body = conduit.post_comment.call_args[0][1]
    assert "Risk: **1/10**" in body
    assert "No findings" in body


def test_process_revision_above_threshold_skips(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    anthropic.messages.create.return_value = _claude_text(json.dumps({
        "risk": 5, "complexity": 7,
        "risk_factors": ["touches auth"], "complexity_factors": ["12 files"],
    }))
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(_rev(), group)
    assert result.posted is False
    assert result.skipped_reason == "above_threshold"
    conduit.post_comment.assert_not_called()


def test_dedup_short_circuits(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    anthropic.messages.create.return_value = _claude_text(json.dumps({
        "risk": 0, "complexity": 0, "risk_factors": [], "complexity_factors": [],
    }))
    group = poller.config.enabled_groups()[0]
    # First run records
    poller.process_revision(_rev(), group, dry_run=True)
    # Second run on same diff → dedup
    result = poller.process_revision(_rev(), group, dry_run=True)
    assert result.posted is False
    assert result.skipped_reason == "dedup"


def test_dry_run_does_not_post(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    anthropic.messages.create.side_effect = [
        _claude_text(json.dumps({"risk": 0, "complexity": 0, "risk_factors": [], "complexity_factors": []})),
        _claude_text("### Looks good\n"),
    ]
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(_rev(), group, dry_run=True)
    assert result.posted is False
    conduit.post_comment.assert_not_called()


def test_oversized_diff_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    conduit.get_raw_diff.return_value = "x" * (poller.config.phabricator.max_diff_bytes + 100)
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(_rev(), group)
    assert result.skipped_reason == "oversized_diff"
    anthropic.messages.create.assert_not_called()


def test_already_accepted_revision_is_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    accepted = Revision(
        phid="PHID-DREV-100",
        id=100,
        title="Already approved",
        summary="",
        status="accepted",
        author_phid="PHID-USER-1",
        repository_phid=None,
        bug_id=None,
        date_created=1716000000,
        date_modified=1716000200,
        reviewer_phids=["PHID-PROJ-ip"],
        project_phids=[],
    )
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(accepted, group, dry_run=True)
    assert result.posted is False
    assert result.skipped_reason == "already_accepted"
    # No diff fetch, no scoring, no comment posted.
    conduit.latest_diff.assert_not_called()
    conduit.get_raw_diff.assert_not_called()
    anthropic.messages.create.assert_not_called()
    conduit.post_comment.assert_not_called()


def test_revision_with_human_comment_is_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    conduit.human_commenter_phids.return_value = {"PHID-USER-bob"}
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(_rev(), group, dry_run=True)
    assert result.posted is False
    assert result.skipped_reason == "already_commented"
    # latest_diff is fetched (we need diff_phid for the dedup check before
    # this skip), but raw_diff fetch and scoring must not happen.
    conduit.get_raw_diff.assert_not_called()
    anthropic.messages.create.assert_not_called()
    conduit.post_comment.assert_not_called()


def test_revision_already_reviewed_by_qreviews_is_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    # Pre-seed the store: qreviews has already posted on a prior diff of
    # this revision.
    rev = _rev()
    poller.store.record_seen(
        revision_phid=rev.phid,
        diff_phid="PHID-DIFF-prior",
        diff_id=99,
        revision_id=rev.id,
        group_slug="ip-protection-reviewers",
        title=rev.title,
        author_phid=rev.author_phid,
        revision_created_at=rev.date_created,
    )
    poller.store.record_reviewed(
        revision_phid=rev.phid,
        diff_phid="PHID-DIFF-prior",
        review_body="prior review",
        model="claude-sonnet-4-6",
        usage={},
        posted=True,
    )
    # New diff appears on the same revision.
    conduit.latest_diff.return_value = _diff(diff_id=2, revision_phid=rev.phid)
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(rev, group, dry_run=True)
    assert result.posted is False
    assert result.skipped_reason == "already_reviewed_by_qreviews"
    # DB short-circuits before the conduit comment-lookup call.
    conduit.human_commenter_phids.assert_not_called()
    conduit.get_raw_diff.assert_not_called()
    anthropic.messages.create.assert_not_called()
    conduit.post_comment.assert_not_called()


def test_revision_authored_by_non_member_is_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    conduit.project_members.return_value = {"PHID-USER-other"}
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(_rev(), group, dry_run=True)
    assert result.posted is False
    assert result.skipped_reason == "author_not_in_group"
    # The membership gate runs before any per-revision Conduit calls.
    conduit.latest_diff.assert_not_called()
    conduit.human_commenter_phids.assert_not_called()
    conduit.get_raw_diff.assert_not_called()
    anthropic.messages.create.assert_not_called()
    conduit.post_comment.assert_not_called()


def _project_lookup(group_phid: str = "PHID-PROJ-ip", secure_phid: str = "PHID-PROJ-secure"):
    """Side-effect resolver mapping slugs to PHIDs so the group resolver and
    the secure-revision resolver return different values from the same mock."""

    def _side(slug: str) -> str | None:
        if slug == "secure-revision":
            return secure_phid
        return group_phid

    return _side


def test_secure_revision_tagged_is_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    conduit.resolve_project_phid.side_effect = _project_lookup()

    tagged = _rev(project_phids=["PHID-PROJ-secure", "PHID-PROJ-other"])
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(tagged, group, dry_run=True)

    assert result.posted is False
    assert result.skipped_reason == "security_sensitive"
    # Must short-circuit before any diff/content fetch and before any
    # Claude call so restricted content never enters our pipeline.
    conduit.latest_diff.assert_not_called()
    conduit.get_raw_diff.assert_not_called()
    conduit.human_commenter_phids.assert_not_called()
    anthropic.messages.create.assert_not_called()
    conduit.post_comment.assert_not_called()


def test_empty_members_lookup_does_not_skip(mocked_poller):
    """A transient empty members result should not silently drop every revision."""
    poller, conduit, anthropic = mocked_poller
    conduit.project_members.return_value = set()
    anthropic.messages.create.side_effect = [
        _claude_text(json.dumps({
            "risk": 0, "complexity": 0, "risk_factors": [], "complexity_factors": [],
        })),
        _claude_text("### Looks good\n"),
    ]
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(_rev(), group, dry_run=True)
    assert result.skipped_reason != "author_not_in_group"


def test_member_restriction_can_be_disabled(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    group = poller.config.enabled_groups()[0]
    group.restrict_to_member_authors = False
    # Author is not in the (mocked) member set, but the gate is off.
    conduit.project_members.return_value = {"PHID-USER-other"}
    anthropic.messages.create.side_effect = [
        _claude_text(json.dumps({
            "risk": 0, "complexity": 0, "risk_factors": [], "complexity_factors": [],
        })),
        _claude_text("### Looks good\n"),
    ]
    result = poller.process_revision(_rev(), group, dry_run=True)
    assert result.skipped_reason != "author_not_in_group"
    # Membership lookup should be skipped entirely when the flag is off.
    conduit.project_members.assert_not_called()


def test_draft_revision_is_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller

    draft = _rev(status="draft")
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(draft, group, dry_run=True)

    assert result.posted is False
    assert result.skipped_reason == "status_draft"
    # Author hasn't requested review — don't fetch the diff, score, or post.
    conduit.latest_diff.assert_not_called()
    conduit.get_raw_diff.assert_not_called()
    conduit.human_commenter_phids.assert_not_called()
    anthropic.messages.create.assert_not_called()
    conduit.post_comment.assert_not_called()


def test_changes_planned_revision_is_skipped(mocked_poller):
    poller, conduit, anthropic = mocked_poller

    wip = _rev(status="changes-planned")
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(wip, group, dry_run=True)

    assert result.posted is False
    assert result.skipped_reason == "status_changes_planned"
    # "Plan Changes" means the author took it back to WIP — stay out.
    conduit.latest_diff.assert_not_called()
    conduit.get_raw_diff.assert_not_called()
    conduit.human_commenter_phids.assert_not_called()
    anthropic.messages.create.assert_not_called()
    conduit.post_comment.assert_not_called()


def test_secure_revision_phid_is_cached_across_calls(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    conduit.resolve_project_phid.side_effect = _project_lookup()
    anthropic.messages.create.return_value = _claude_text(
        json.dumps({"risk": 5, "complexity": 5, "risk_factors": [], "complexity_factors": []})
    )

    group = poller.config.enabled_groups()[0]
    # Two untagged revisions go through the pipeline; the secure-revision
    # PHID resolves once and is reused on the second call.
    poller.process_revision(_rev(revision_id=100), group, dry_run=True)
    poller.process_revision(_rev(revision_id=101), group, dry_run=True)

    secure_calls = [
        c for c in conduit.resolve_project_phid.call_args_list
        if c.args and c.args[0] == "secure-revision"
    ]
    assert len(secure_calls) == 1


def test_unresolvable_secure_revision_slug_does_not_block_reviews(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    # Slug doesn't resolve (returns None for secure-revision) — the poller
    # logs a warning and proceeds with the rest of the pipeline.
    conduit.resolve_project_phid.side_effect = _project_lookup(secure_phid=None)
    anthropic.messages.create.side_effect = [
        _claude_text(json.dumps({
            "risk": 1, "complexity": 1, "risk_factors": [], "complexity_factors": [],
        })),
        _claude_text("### Looks good\n"),
    ]
    # Skill needed for the review step on this group.
    group = poller.config.enabled_groups()[0]

    result = poller.process_revision(_rev(), group, dry_run=True)
    # Pipeline ran (scoring + review) even though the secure-revision
    # slug couldn't be resolved.
    assert result.skipped_reason != "security_sensitive"
    conduit.latest_diff.assert_called_once()


def test_poll_group_advances_watermark(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    anthropic.messages.create.return_value = _claude_text(json.dumps({
        "risk": 5, "complexity": 5, "risk_factors": [], "complexity_factors": [],
    }))
    group = poller.config.enabled_groups()[0]
    poller.poll_group(group, dry_run=True)
    assert poller.store.get_watermark(group.slug) == 1716000100


def test_additional_skill_paths_for_excludes_primary(mocked_poller, tmp_path):
    poller, conduit, _ = mocked_poller

    # Stand up a fake skills/ tree and point the poller at it.
    skills_root = tmp_path / "skills"
    (skills_root / "desktop-theme-review").mkdir(parents=True)
    (skills_root / "desktop-theme-review" / "SKILL.md").write_text("DT body")
    (skills_root / "ip-protection-review").mkdir()
    (skills_root / "ip-protection-review" / "SKILL.md").write_text("IP body")
    poller._skills_root = lambda: skills_root  # type: ignore[method-assign]

    conduit.resolve_project_phids.return_value = {
        "desktop-theme-reviewers": "PHID-PROJ-dt",
        "ip-protection-reviewers": "PHID-PROJ-ip",
    }

    rev = Revision(
        phid="PHID-DREV-200",
        id=200,
        title="x",
        summary="",
        status="needs-review",
        author_phid="PHID-USER-1",
        repository_phid=None,
        bug_id=None,
        date_created=0,
        date_modified=0,
        # Both groups tagged on this revision.
        reviewer_phids=["PHID-PROJ-ip", "PHID-PROJ-dt", "PHID-USER-bob"],
        project_phids=[],
    )

    paths = poller.additional_skill_paths_for(rev, primary_phid="PHID-PROJ-ip")
    # Primary (ip) excluded; supplemental (dt) included; user PHID ignored.
    assert paths == [str(skills_root / "desktop-theme-review" / "SKILL.md")]


def test_process_revision_threads_supplemental_skills_into_review(
    mocked_poller, tmp_path
):
    poller, conduit, anthropic = mocked_poller

    skills_root = tmp_path / "skills"
    (skills_root / "desktop-theme-review").mkdir(parents=True)
    (skills_root / "desktop-theme-review" / "SKILL.md").write_text(
        "---\ndescription: x\n---\nDESKTOP THEME RULES"
    )
    poller._skills_root = lambda: skills_root  # type: ignore[method-assign]
    conduit.resolve_project_phids.return_value = {
        "desktop-theme-reviewers": "PHID-PROJ-dt",
    }

    rev = _rev()
    # Add the desktop-theme group as an additional reviewer.
    rev = Revision(**{**rev.__dict__, "reviewer_phids": [*rev.reviewer_phids, "PHID-PROJ-dt"]})

    anthropic.messages.create.side_effect = [
        _claude_text(json.dumps({
            "risk": 1, "complexity": 1,
            "risk_factors": [], "complexity_factors": [],
        })),
        _claude_text("### ok\nlooks fine"),
    ]
    group = poller.config.enabled_groups()[0]
    result = poller.process_revision(rev, group, dry_run=True)
    assert result.posted is False  # dry_run, but review still generated

    # The review-generation call (second messages.create) must have the
    # desktop-theme skill body in the system prompt.
    review_call = anthropic.messages.create.call_args_list[1]
    system_text = review_call.kwargs["system"][0]["text"]
    assert "DESKTOP THEME RULES" in system_text
    assert "Additional reviewer-group context" in system_text
