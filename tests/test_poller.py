"""Poller — end-to-end with mocked Conduit + Anthropic."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qreviews.conduit import Diff, Revision
from qreviews.poller import Poller


def _rev(revision_id: int = 100) -> Revision:
    return Revision(
        phid=f"PHID-DREV-{revision_id}",
        id=revision_id,
        title="Fix the thing",
        summary="It was broken.",
        status="needs-review",
        author_phid="PHID-USER-1",
        repository_phid="PHID-REPO-1",
        bug_id="9999",
        date_created=1716000000,
        date_modified=1716000100,
        reviewer_phids=["PHID-PROJ-ip"],
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


def test_poll_group_advances_watermark(mocked_poller):
    poller, conduit, anthropic = mocked_poller
    anthropic.messages.create.return_value = _claude_text(json.dumps({
        "risk": 5, "complexity": 5, "risk_factors": [], "complexity_factors": [],
    }))
    group = poller.config.enabled_groups()[0]
    poller.poll_group(group, dry_run=True)
    assert poller.store.get_watermark(group.slug) == 1716000100
