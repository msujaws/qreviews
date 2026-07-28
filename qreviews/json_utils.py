"""Small JSON helpers shared between scoring and review.

Both prompts ask Claude to terminate with a JSON object. Claude
sometimes wraps the JSON in ```json fences or prepends prose; these
helpers recover the payload from that surrounding noise.

The naive approach — a greedy `\\{.*\\}` regex — breaks when the
response contains more than one JSON object, because the span runs
from the first `{` to the last `}` and picks up the prose between
them. That is what published a model's raw chain of thought on
D313322. Scan for complete objects instead, and let callers name the
keys the payload must carry so a truncated response raises rather
than yielding a wrong-shaped object.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text


def find_json_objects(
    text: str, *, required_keys: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Return every complete JSON object in `text`, in order of appearance.

    Objects nested inside another decoded object are not reported
    separately. When `required_keys` is non-empty, only objects carrying
    all of those top-level keys are returned.
    """
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    i = 0
    while True:
        start = text.find("{", i)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            i = start + 1
            continue
        if isinstance(obj, dict):
            found.append(obj)
        # Skip past the decoded value so nested objects aren't double-counted.
        i = end
    if required_keys:
        found = [obj for obj in found if all(k in obj for k in required_keys)]
    return found


def extract_json_object(
    text: str, *, required_keys: Sequence[str] = ()
) -> dict[str, Any]:
    """Parse a JSON object from `text`, tolerating fences or surrounding prose.

    When the text holds several objects, the last one wins — models that
    revise themselves put the final answer last. Callers that care about
    the payload shape should pass `required_keys`; candidates missing any
    of them are ignored, so a truncated response raises instead of
    returning an inner fragment.

    Raises `json.JSONDecodeError` if no matching JSON object can be found.
    """
    stripped = _strip_fences(text)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as first_error:
        candidates = find_json_objects(stripped, required_keys=required_keys)
        if not candidates:
            raise first_error
        return candidates[-1]
    if not isinstance(payload, dict) or (
        required_keys and not all(k in payload for k in required_keys)
    ):
        raise json.JSONDecodeError(
            f"JSON payload is missing required keys {tuple(required_keys)}",
            stripped,
            0,
        )
    return payload
