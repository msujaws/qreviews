"""The model critic that gates a review before it is posted."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from qreviews.critic import (
    CRITIC_SYSTEM_PROMPT,
    VERDICT_TOOL,
    CriticVerdict,
    apply_verdict,
    critique_review,
)
from qreviews.review import Finding


def _finding(path: str = "dom/foo/Bar.cpp", line: int = 117, body: str = "Fix it.") -> Finding:
    return Finding(file_path=path, line=line, is_new_file=True, body=body, confidence=0.9)


def _verdict_response(**payload) -> SimpleNamespace:
    full = {
        "approved": True,
        "block_reasons": [],
        "drop_summary": False,
        "drop_finding_indices": [],
        **payload,
    }
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="report_verdict", id="tu1", input=full)],
        stop_reason="tool_use",
        usage=SimpleNamespace(
            input_tokens=300,
            output_tokens=40,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def _critique(client, **kwargs):
    defaults = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "revision_id": 313322,
        "title": "Bug 1 - Fix the thing",
        "summary": "",
        "findings": [_finding()],
    }
    return critique_review(client, **{**defaults, **kwargs})


# --------------------------------------------------------------------- verdicts


def test_approve_keeps_everything():
    client = MagicMock()
    client.messages.create.return_value = _verdict_response()
    verdict = _critique(client)
    assert verdict.approved is True
    assert verdict.errored is False
    assert verdict.skipped is False
    assert verdict.drop_finding_indices == []
    assert verdict.usage["input_tokens"] == 300
    assert verdict.model == "claude-haiku-4-5-20251001"


def test_block_records_reasons():
    client = MagicMock()
    client.messages.create.return_value = _verdict_response(
        approved=False, block_reasons=["leaks the model's reasoning"]
    )
    verdict = _critique(client)
    assert verdict.approved is False
    assert verdict.block_reasons == ["leaks the model's reasoning"]


def test_drop_indices_apply_to_the_named_findings():
    client = MagicMock()
    client.messages.create.return_value = _verdict_response(drop_finding_indices=[1])
    findings = [_finding(body="keep"), _finding(body="drop"), _finding(body="keep too")]
    verdict = _critique(client, findings=findings)
    summary, kept = apply_verdict(verdict, summary="s", findings=findings)
    assert [f.body for f in kept] == ["keep", "keep too"]
    assert summary == "s"


def test_drop_summary_keeps_findings():
    client = MagicMock()
    client.messages.create.return_value = _verdict_response(drop_summary=True)
    findings = [_finding()]
    verdict = _critique(client, summary="Looks fine.", findings=findings)
    summary, kept = apply_verdict(verdict, summary="Looks fine.", findings=findings)
    assert summary == ""
    assert len(kept) == 1


def test_out_of_range_index_is_ignored():
    client = MagicMock()
    client.messages.create.return_value = _verdict_response(drop_finding_indices=[0, 99, -3])
    findings = [_finding(body="only one")]
    verdict = _critique(client, findings=findings)
    assert verdict.drop_finding_indices == [0]
    _, kept = apply_verdict(verdict, summary="", findings=findings)
    assert kept == []


# ----------------------------------------------------------------- call shape


def test_forced_tool_use_and_no_raw_diff():
    client = MagicMock()
    client.messages.create.return_value = _verdict_response()
    _critique(client, diff_excerpts={0: "@@ -1 +1 @@\n+int b = 3;"})
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tools"] == [VERDICT_TOOL]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "report_verdict"}
    assert kwargs["system"][0]["text"] == CRITIC_SYSTEM_PROMPT
    sent = kwargs["messages"][0]["content"]
    # Contributor-authored text is tagged as data, not instructions.
    assert '<finding index="0"' in sent
    assert "<diff_context>" in sent
    assert "+int b = 3;" in sent


def test_missing_excerpt_is_reported_not_omitted():
    client = MagicMock()
    client.messages.create.return_value = _verdict_response()
    _critique(client)
    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "(not found in the diff)" in sent


# ---------------------------------------------------------------- edge cases


def test_nothing_to_critique_makes_no_api_call():
    client = MagicMock()
    verdict = _critique(client, summary="", findings=[])
    assert verdict.skipped is True
    assert verdict.approved is True
    client.messages.create.assert_not_called()


def test_api_failure_fails_closed_by_default():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("503")
    verdict = _critique(client)
    assert verdict.errored is True
    assert verdict.approved is False
    assert verdict.block_reasons


def test_api_failure_can_fail_open():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("503")
    verdict = _critique(client, fail_open=True)
    assert verdict.errored is True
    assert verdict.approved is True


def test_missing_tool_use_block_fails_closed():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="I think it is fine.")],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    verdict = _critique(client)
    assert verdict.errored is True
    assert verdict.approved is False


def test_malformed_tool_input_fails_closed():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="report_verdict", id="t", input={})],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    verdict = _critique(client)
    assert verdict.errored is True
    assert verdict.approved is False


def test_apply_verdict_on_a_skipped_critic_is_a_no_op():
    findings = [_finding()]
    summary, kept = apply_verdict(
        CriticVerdict(skipped=True), summary="s", findings=findings
    )
    assert summary == "s"
    assert kept == findings
