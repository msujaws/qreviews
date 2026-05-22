"""Scoring — JSON parsing + Anthropic mocking."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qreviews.scoring import _extract_json, score_revision


def _fake_response(json_text: str, usage: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json_text)],
        usage=SimpleNamespace(
            input_tokens=(usage or {}).get("input", 100),
            output_tokens=(usage or {}).get("output", 20),
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose():
    text = 'Sure! Here is the score:\n{"risk": 1, "complexity": 2}\nLet me know.'
    assert _extract_json(text) == {"risk": 1, "complexity": 2}


def test_score_revision_happy_path():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        json.dumps(
            {
                "risk": 1,
                "complexity": 0,
                "risk_factors": ["only docs"],
                "complexity_factors": ["1 line"],
            }
        )
    )
    res = score_revision(
        client,
        model="claude-haiku-4-5",
        max_tokens=512,
        title="t",
        summary="s",
        revision_id=1,
        author_phid="u",
        bug_id=None,
        raw_diff="@@ -1 +1 @@\n-old\n+new",
    )
    assert res.scores.risk == 1
    assert res.scores.complexity == 0
    assert res.scores.risk_factors == ["only docs"]
    assert res.usage["input_tokens"] == 100
    # Verify the call shape — system prompt is sent as a cache-controlled block.
    args, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_score_revision_bad_json_raises():
    client = MagicMock()
    client.messages.create.return_value = _fake_response("nonsense, no json here")
    with pytest.raises((json.JSONDecodeError, ValueError)):
        score_revision(
            client,
            model="claude-haiku-4-5",
            max_tokens=512,
            title="t",
            summary="s",
            revision_id=1,
            author_phid="u",
            bug_id=None,
            raw_diff="@@",
        )
