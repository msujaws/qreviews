"""generate_review() prompt assembly — primary + supplemental skills, and
tool-availability gating.

The gating tests guard against the regression that produced D302271 /
D302524: the prompt promised "searchfox tools" even when searchfox-cli
wasn't installed at runtime, so Claude tried a tool call, got an error,
and apologised in the public review body.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from qreviews.review import SUPPLEMENTAL_SKILLS_HEADER, generate_review


def _claude_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _write_skill(path: Path, body: str) -> str:
    path.write_text(f"---\ndescription: x\n---\n{body}")
    return str(path)


def test_generate_review_without_supplemental(tmp_path: Path):
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY GUIDANCE BODY")

    client = MagicMock()
    client.messages.create.return_value = _claude_response("final review text")

    result = generate_review(
        client,
        model="claude-sonnet-test",
        max_tokens=128,
        skill_path=primary,
        title="t",
        summary="s",
        revision_id=1,
        author_phid="PHID-USER-1",
        bug_id=None,
        raw_diff="@@",
        enable_tools=False,
    )

    assert result.body == "final review text"
    system_text = client.messages.create.call_args.kwargs["system"][0]["text"]
    assert "PRIMARY GUIDANCE BODY" in system_text
    assert SUPPLEMENTAL_SKILLS_HEADER not in system_text


def test_generate_review_appends_supplemental_bodies(tmp_path: Path):
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY GUIDANCE BODY")
    extra_a = _write_skill(tmp_path / "extra_a.md", "EXTRA_A BODY")
    extra_b = _write_skill(tmp_path / "extra_b.md", "EXTRA_B BODY")

    client = MagicMock()
    client.messages.create.return_value = _claude_response("ok")

    generate_review(
        client,
        model="claude-sonnet-test",
        max_tokens=128,
        skill_path=primary,
        title="t",
        summary="s",
        revision_id=1,
        author_phid="PHID-USER-1",
        bug_id=None,
        raw_diff="@@",
        additional_skill_paths=[extra_a, extra_b],
        enable_tools=False,
    )

    system_text = client.messages.create.call_args.kwargs["system"][0]["text"]
    assert "PRIMARY GUIDANCE BODY" in system_text
    assert SUPPLEMENTAL_SKILLS_HEADER.strip() in system_text
    assert "EXTRA_A BODY" in system_text
    assert "EXTRA_B BODY" in system_text
    # Primary appears before the supplemental header.
    assert system_text.index("PRIMARY GUIDANCE BODY") < system_text.index(
        "Additional reviewer-group context"
    )


def test_prompt_omits_searchfox_when_unavailable(mocker, tmp_path: Path):
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY GUIDANCE")
    mocker.patch("qreviews.review.has_searchfox", return_value=False)
    client = MagicMock()
    client.messages.create.return_value = _claude_response("ok")

    generate_review(
        client,
        model="claude-test",
        max_tokens=128,
        skill_path=primary,
        title="t",
        summary="s",
        revision_id=1,
        author_phid="PHID-USER-1",
        bug_id=None,
        raw_diff="@@",
    )

    sent = client.messages.create.call_args.kwargs
    system_text = sent["system"][0]["text"]
    assert "searchfox" not in system_text.lower()
    assert "find_definition" not in system_text
    assert "tools" not in sent  # no tools param sent to the API


def test_prompt_includes_searchfox_when_available(mocker, tmp_path: Path):
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY GUIDANCE")
    mocker.patch("qreviews.review.has_searchfox", return_value=True)
    client = MagicMock()
    client.messages.create.return_value = _claude_response("ok")

    generate_review(
        client,
        model="claude-test",
        max_tokens=128,
        skill_path=primary,
        title="t",
        summary="s",
        revision_id=1,
        author_phid="PHID-USER-1",
        bug_id=None,
        raw_diff="@@",
    )

    sent = client.messages.create.call_args.kwargs
    system_text = sent["system"][0]["text"]
    assert "searchfox" in system_text.lower()
    assert "find_definition" in system_text
    assert sent.get("tools") is not None


def test_explicit_enable_tools_false_skips_probe(mocker, tmp_path: Path):
    """Caller can force tool-less mode even when searchfox would resolve."""
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY GUIDANCE")
    probe = mocker.patch("qreviews.review.has_searchfox", return_value=True)
    client = MagicMock()
    client.messages.create.return_value = _claude_response("ok")

    generate_review(
        client,
        model="claude-test",
        max_tokens=128,
        skill_path=primary,
        title="t",
        summary="s",
        revision_id=1,
        author_phid="PHID-USER-1",
        bug_id=None,
        raw_diff="@@",
        enable_tools=False,
    )

    probe.assert_not_called()
    system_text = client.messages.create.call_args.kwargs["system"][0]["text"]
    assert "searchfox" not in system_text.lower()
