"""generate_review() prompt assembly — primary + supplemental skills, and
tool-availability gating.

The gating tests guard against the regression that produced D302271 /
D302524: the prompt promised "searchfox tools" even when searchfox-cli
wasn't installed at runtime, so Claude tried a tool call, got an error,
and apologised in the public review body.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from qreviews.review import (
    SUPPLEMENTAL_SKILLS_HEADER,
    generate_review,
    parse_review_payload,
)


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


def _json_response(summary: str = "", findings: list[dict] | None = None) -> SimpleNamespace:
    payload = json.dumps({"summary": summary, "findings": findings or []})
    return _claude_response(payload)


def _write_skill(path: Path, body: str) -> str:
    path.write_text(f"---\ndescription: x\n---\n{body}")
    return str(path)


def test_generate_review_without_supplemental(tmp_path: Path):
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY GUIDANCE BODY")

    client = MagicMock()
    client.messages.create.return_value = _json_response(summary="all good")

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

    assert result.summary == "all good"
    assert result.findings == []
    assert result.parse_failed is False
    system_text = client.messages.create.call_args.kwargs["system"][0]["text"]
    assert "PRIMARY GUIDANCE BODY" in system_text
    assert SUPPLEMENTAL_SKILLS_HEADER not in system_text


def test_generate_review_appends_supplemental_bodies(tmp_path: Path):
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY GUIDANCE BODY")
    extra_a = _write_skill(tmp_path / "extra_a.md", "EXTRA_A BODY")
    extra_b = _write_skill(tmp_path / "extra_b.md", "EXTRA_B BODY")

    client = MagicMock()
    client.messages.create.return_value = _json_response()

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
    client.messages.create.return_value = _json_response()

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
    client.messages.create.return_value = _json_response()

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
    client.messages.create.return_value = _json_response()

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


def test_user_message_embeds_test_signals_block(tmp_path: Path):
    primary = _write_skill(tmp_path / "primary.md", "PRIMARY")
    client = MagicMock()
    client.messages.create.return_value = _json_response()

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
        test_signals_block="<test_signals>\n  in_diff_test_signal=absent\n</test_signals>",
    )

    sent_user = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "<test_signals>" in sent_user
    assert "in_diff_test_signal=absent" in sent_user


# ---------------------------------------------------------------- parse_review_payload


_LEGAL = frozenset(
    {
        ("dom/foo/Bar.cpp", 117, True),
        ("dom/foo/Bar.cpp", 118, True),
        ("dom/foo/Bar.cpp", 50, False),
    }
)


def test_parse_review_payload_happy_path():
    raw = json.dumps(
        {
            "summary": "all clear",
            "findings": [
                {
                    "file_path": "dom/foo/Bar.cpp",
                    "line": 117,
                    "is_new_file": True,
                    "body": "Remove the unused param.",
                    "confidence": 0.9,
                }
            ],
        }
    )
    res = parse_review_payload(raw, legal_anchors=_LEGAL)
    assert res.summary == "all clear"
    assert len(res.findings) == 1
    assert res.findings[0].file_path == "dom/foo/Bar.cpp"
    assert res.findings[0].line == 117
    assert res.findings[0].confidence == 0.9
    assert res.parse_failed is False
    assert res.rejected_count == 0


def test_parse_review_payload_rejects_invalid_anchor():
    raw = json.dumps(
        {
            "summary": "",
            "findings": [
                {
                    "file_path": "dom/foo/Bar.cpp",
                    "line": 117,
                    "is_new_file": True,
                    "body": "valid",
                },
                {
                    "file_path": "dom/foo/Bar.cpp",
                    "line": 9999,
                    "is_new_file": True,
                    "body": "hallucinated line",
                },
            ],
        }
    )
    res = parse_review_payload(raw, legal_anchors=_LEGAL)
    assert len(res.findings) == 1
    assert res.findings[0].body == "valid"
    assert res.rejected_count == 1
    assert "hallucinated line" in res.summary


def test_parse_review_payload_falls_back_on_non_json():
    res = parse_review_payload("just some prose, no json", legal_anchors=_LEGAL)
    assert res.parse_failed is True
    assert res.summary == "just some prose, no json"
    assert res.findings == []


def test_parse_review_payload_handles_fenced_json():
    raw = "```json\n" + json.dumps({"summary": "fenced", "findings": []}) + "\n```"
    res = parse_review_payload(raw, legal_anchors=_LEGAL)
    assert res.summary == "fenced"


def test_parse_review_payload_skips_malformed_finding_entries():
    raw = json.dumps(
        {
            "summary": "",
            "findings": [
                {"file_path": "", "line": 1, "body": "empty path"},
                {"file_path": "x", "line": "not-an-int", "body": "bad line"},
                {"file_path": "x", "line": 1, "body": ""},
                "not-a-dict",
            ],
        }
    )
    res = parse_review_payload(raw)
    assert res.findings == []
