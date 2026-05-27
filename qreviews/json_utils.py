"""Small JSON helpers shared between scoring and review.

Both prompts ask Claude to terminate with a JSON object. Claude
sometimes wraps the JSON in ```json fences or prepends prose; this
helper strips those wrappers before delegating to `json.loads`.
"""

from __future__ import annotations

import json
import re
from typing import Any

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from `text`, tolerating fences or surrounding prose.

    Raises `json.JSONDecodeError` if no JSON object can be found.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match:
            return json.loads(match.group(0))
        raise
