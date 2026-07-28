"""JSON recovery from model responses that carry prose and fences."""

from __future__ import annotations

import json

import pytest

from qreviews.json_utils import extract_json_object, find_json_objects

# The shape that published a chain of thought on D313322: an answer, a
# self-correction in prose, then a revised answer. The old greedy
# `\{.*\}` regex spanned both objects and failed to parse.
D313322_SHAPE = """\
The code change and tests look correct. One minor doc issue worth flagging:

```json
{
  "summary": "",
  "findings": [
    {
      "file_path": "browser/components/asrouter/docs/targeting-guide.md",
      "line": 88,
      "is_new_file": true,
      "body": "Move the section next to its siblings.",
      "confidence": 0.5
    }
  ]
}
```

Wait — let me re-check that. That's actually a coherent grouping. I'll drop
this marginal finding.

```json
{
  "summary": "",
  "findings": []
}
```
"""


def test_plain_object():
    assert extract_json_object('{"risk": 1, "complexity": 2}') == {
        "risk": 1,
        "complexity": 2,
    }


def test_fenced_object():
    text = '```json\n{"risk": 1, "complexity": 2}\n```'
    assert extract_json_object(text)["risk"] == 1


def test_prose_prefixed_object():
    text = 'Here are the scores:\n{"risk": 1, "complexity": 2}'
    assert extract_json_object(text)["complexity"] == 2


def test_two_payloads_returns_the_last_one():
    # Regression for D313322: the greedy regex raised here, which sent the
    # whole raw response downstream as the comment body.
    payload = extract_json_object(D313322_SHAPE, required_keys=("summary", "findings"))
    assert payload == {"summary": "", "findings": []}


def test_find_json_objects_counts_both_payloads():
    found = find_json_objects(D313322_SHAPE, required_keys=("summary", "findings"))
    assert len(found) == 2
    assert len(found[0]["findings"]) == 1
    assert found[1]["findings"] == []


def test_nested_objects_are_not_counted_separately():
    text = '{"summary": "", "findings": [{"file_path": "a.js", "line": 1}]}'
    assert len(find_json_objects(text)) == 1


def test_truncated_payload_raises_rather_than_yielding_a_fragment():
    # The outer object never closes, so the only complete object is an
    # inner finding. Returning it would post a silent, vacuous review.
    text = (
        'Here is the review:\n{"summary": "", "findings": [\n'
        '  {"file_path": "a.js", "line": 4, "is_new_file": true, "body": "Fix it."},\n'
        '  {"file_path": "b.js"'
    )
    assert find_json_objects(text) != []
    with pytest.raises(json.JSONDecodeError):
        extract_json_object(text, required_keys=("summary", "findings"))


def test_required_keys_filter_ignores_wrong_shaped_objects():
    text = 'Config: {"model": "haiku"}\nScores: {"risk": 3, "complexity": 2}'
    assert extract_json_object(text, required_keys=("risk", "complexity"))["risk"] == 3


def test_missing_required_keys_on_a_bare_object_raises():
    with pytest.raises(json.JSONDecodeError):
        extract_json_object('{"model": "haiku"}', required_keys=("risk", "complexity"))


def test_no_json_raises():
    with pytest.raises(json.JSONDecodeError):
        extract_json_object("No JSON here at all.")


def test_prose_with_stray_braces_still_finds_the_payload():
    text = 'The literal {} is empty. Scores: {"risk": 0, "complexity": 1}'
    assert extract_json_object(text, required_keys=("risk", "complexity"))["complexity"] == 1
