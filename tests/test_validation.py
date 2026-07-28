"""Deterministic pre-post validation of review output."""

from __future__ import annotations

from qreviews.review import Finding, ReviewResult
from qreviews.validation import validate_rendered_body, validate_review

DEFAULTS = {
    "min_confidence": 0.7,
    "max_summary_chars": 1200,
    "max_finding_chars": 800,
}


def _finding(body: str = "Remove the unused parameter.", confidence: float = 0.9) -> Finding:
    return Finding(
        file_path="dom/foo/Bar.cpp",
        line=117,
        is_new_file=True,
        body=body,
        confidence=confidence,
    )


def _validate(review: ReviewResult):
    return validate_review(review, **DEFAULTS)


def _codes(rejections) -> set[str]:
    return {r.code for r in rejections}


# --------------------------------------------------------------- happy path


def test_clean_review_passes_untouched():
    out = _validate(ReviewResult(summary="", findings=[_finding()]))
    assert out.ok
    assert out.skip_reason is None
    assert len(out.findings) == 1
    assert out.findings[0].body == "Remove the unused parameter."


def test_empty_review_passes():
    out = _validate(ReviewResult(summary=""))
    assert out.ok
    assert out.findings == []


# ------------------------------------------------- tier A: reject whole post


def test_parse_failed_rejects():
    out = _validate(ReviewResult(summary="raw prose", parse_failed=True))
    assert not out.ok
    assert out.skip_reason == "validation_parse_failed"


def test_two_competing_payloads_reject():
    # D313322: the model answered, second-guessed itself, and answered again.
    out = _validate(ReviewResult(summary="", payload_candidates=2))
    assert not out.ok
    assert out.skip_reason == "validation_ambiguous_payloads"


def test_leaked_json_payload_in_summary_rejects():
    summary = 'One issue:\n\n```json\n{\n  "summary": "",\n  "findings": []\n}\n```'
    out = _validate(ReviewResult(summary=summary))
    assert not out.ok
    assert "leaked_payload" in _codes(out.rejections)


def test_leaked_schema_keys_reject():
    summary = 'Output was "file_path": "a.js" and "is_new_file": true.'
    out = _validate(ReviewResult(summary=summary))
    assert not out.ok
    assert "leaked_schema_keys" in _codes(out.rejections)


def test_single_schema_key_alone_does_not_reject():
    # A lone quoted key can plausibly appear in a Firefox JSON blob.
    out = _validate(ReviewResult(summary='The manifest sets "confidence": 0.5 here.'))
    assert out.ok


def test_leaked_scaffolding_rejects():
    out = _validate(ReviewResult(summary="----- BEGIN DIFF -----\n+ new line"))
    assert not out.ok
    assert "leaked_scaffolding" in _codes(out.rejections)


def test_step_heading_rejects():
    out = _validate(ReviewResult(summary="**Step 1 — Analyze the changes.**"))
    assert not out.ok
    assert "leaked_scaffolding" in _codes(out.rejections)


def test_verdict_language_rejects():
    out = _validate(ReviewResult(summary="This looks correct, r+ from the bot."))
    assert not out.ok
    assert "verdict_language" in _codes(out.rejections)


def test_rvalue_does_not_read_as_a_review_flag():
    out = _validate(
        ReviewResult(summary="", findings=[_finding(body="Take the parameter by r-value reference.")])
    )
    assert out.ok
    assert len(out.findings) == 1


def test_adjectival_approved_does_not_reject():
    out = _validate(
        ReviewResult(summary="", findings=[_finding(body="Add the host to the approved origins list.")])
    )
    assert out.ok


def test_first_person_thinking_rejects():
    out = _validate(ReviewResult(summary="I checked the callers and they are fine."))
    assert not out.ok
    assert "leaked_thinking" in _codes(out.rejections)


def test_self_correction_rejects():
    out = _validate(ReviewResult(summary="Wait — let me re-check that one."))
    assert not out.ok
    assert "leaked_thinking" in _codes(out.rejections)


def test_io_does_not_read_as_first_person():
    out = _validate(ReviewResult(summary="The I/O happens off the main thread."))
    assert out.ok


def test_await_does_not_read_as_self_correction():
    out = _validate(
        ReviewResult(summary="", findings=[_finding(body="The caller must wait for the promise.")])
    )
    assert out.ok
    assert len(out.findings) == 1


def test_verdict_language_in_a_finding_rejects_the_post():
    out = _validate(ReviewResult(summary="", findings=[_finding(body="Fine as-is, approving.")]))
    assert not out.ok


# ------------------------------------------- tier B: clear summary, keep inlines


def test_hedged_summary_is_cleared_but_findings_survive():
    out = _validate(
        ReviewResult(
            summary="Maybe consider adding a test for this case.",
            findings=[_finding()],
        )
    )
    assert out.ok
    assert out.summary == ""
    assert len(out.findings) == 1
    assert "hedging" in _codes(out.dropped)


def test_praise_summary_is_cleared():
    out = _validate(ReviewResult(summary="Looks good overall."))
    assert out.ok
    assert out.summary == ""
    assert "praise" in _codes(out.dropped)


def test_score_restatement_clears_the_summary():
    out = _validate(ReviewResult(summary="The risk here is low."))
    assert out.ok
    assert out.summary == ""
    assert "restates_scores" in _codes(out.dropped)


def test_over_long_summary_is_cleared():
    out = _validate(ReviewResult(summary="x" * 2000))
    assert out.ok
    assert out.summary == ""
    assert "too_long" in _codes(out.dropped)


def test_clean_summary_survives():
    out = _validate(ReviewResult(summary="This commit lacks a corresponding test file."))
    assert out.ok
    assert out.summary == "This commit lacks a corresponding test file."


# ------------------------------------------------- tier C: drop one finding


def test_low_confidence_finding_dropped_while_siblings_survive():
    out = _validate(
        ReviewResult(
            summary="",
            findings=[
                _finding(body="Confident finding.", confidence=0.9),
                _finding(body="Marginal finding.", confidence=0.4),
            ]
        )
    )
    assert out.ok
    assert [f.body for f in out.findings] == ["Confident finding."]
    assert "low_confidence" in _codes(out.dropped)


def test_hedged_finding_is_dropped_not_rejected():
    out = _validate(ReviewResult(summary="", findings=[_finding(body="Maybe rename this.")]))
    assert out.ok
    assert out.findings == []
    assert "hedging" in _codes(out.dropped)


def test_all_findings_dropped_still_passes():
    out = _validate(ReviewResult(summary="", findings=[_finding(confidence=0.1)]))
    assert out.ok
    assert out.findings == []


def test_over_long_finding_is_dropped():
    out = _validate(ReviewResult(summary="", findings=[_finding(body="Fix it. " + "x" * 900)]))
    assert out.ok
    assert out.findings == []
    assert "too_long" in _codes(out.dropped)


def test_exclamation_in_a_finding_is_dropped():
    out = _validate(ReviewResult(summary="", findings=[_finding(body="Drop this branch!")]))
    assert out.ok
    assert out.findings == []
    assert "exclamation" in _codes(out.dropped)


# ------------------------- code spans are invisible to the voice checks


def test_identifier_containing_consider_survives():
    out = _validate(
        ReviewResult(summary="", findings=[_finding(body="Rename `shouldConsider` to `isEligible`.")])
    )
    assert out.ok
    assert len(out.findings) == 1


def test_negation_operator_does_not_read_as_an_exclamation():
    out = _validate(
        ReviewResult(summary="", findings=[_finding(body="Guard with `if (!x)` before the deref.")])
    )
    assert out.ok
    assert len(out.findings) == 1


def test_css_important_does_not_read_as_an_exclamation():
    out = _validate(
        ReviewResult(summary="", findings=[_finding(body="Drop `!important` from the rule.")])
    )
    assert out.ok
    assert len(out.findings) == 1


def test_quoted_schema_key_inside_a_fence_still_rejects():
    # Leak checks deliberately run on raw text: a leaked payload lives
    # inside a fence.
    body = 'Emitted:\n```json\n{"file_path": "a.js", "confidence": 0.9}\n```'
    out = _validate(ReviewResult(summary="", findings=[_finding(body=body)]))
    assert not out.ok


# --------------------------------------------------- tier D: sanitize only


def test_emoji_is_stripped_not_rejected():
    out = _validate(ReviewResult(summary="", findings=[_finding(body="Fix the leak. 🤖")]))
    assert out.ok
    assert len(out.findings) == 1
    assert "🤖" not in out.findings[0].body
    assert out.findings[0].body == "Fix the leak."


def test_stray_fence_markers_are_stripped():
    out = _validate(ReviewResult(summary="```\nUse a helper here.\n```"))
    assert out.ok
    assert "```" not in out.summary


# ------------------------------------------------------------ rendered body


def test_clean_rendered_body_passes():
    body = (
        "**qreviews — no inline findings**\n\n"
        "Risk 1/10, complexity 0/10.\n\n---\n"
        "*Advisory only — posted by qreviews. Does not accept, reject, "
        "or request changes.*\n"
    )
    assert validate_rendered_body(body, max_chars=6000) == []


def test_rendered_body_rejects_a_leaked_payload():
    body = '**qreviews**\n\n```json\n{"summary": "", "findings": []}\n```\n'
    assert _codes(validate_rendered_body(body, max_chars=6000)) >= {"leaked_payload"}


def test_rendered_body_rejects_emoji():
    assert "emoji" in _codes(validate_rendered_body("**qreviews** 🤖", max_chars=6000))


def test_rendered_body_rejects_over_length():
    assert "too_long" in _codes(validate_rendered_body("x" * 100, max_chars=50))


# ------------------------------------------------------------------ detail


def test_detail_serializes_rejections_and_drops():
    out = _validate(
        ReviewResult(
            summary="Looks good.",
            findings=[_finding(confidence=0.1)],
            parse_failed=True,
        )
    )
    detail = out.detail()
    assert any("parse_failed" in r for r in detail["rejections"])
    assert any("low_confidence" in d for d in detail["dropped"])
