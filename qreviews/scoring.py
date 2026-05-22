"""Risk + complexity scoring via Claude.

One call per fresh diff. Returns strict JSON parsed into a Scores object.
Token usage is captured so the dashboard can show cost.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)


SCORING_SYSTEM_PROMPT = """\
You are a senior Mozilla Firefox reviewer. Rate an incoming Phabricator
revision on two integer 0-10 axes. You MUST use the full 0-10 range —
trivial changes deserve scores of 0 or 1, not 2 or 3.

  - RISK: blast radius if this change is wrong. Considers sensitive
    components (security, IPC, prefs, permissions, crypto, sandbox,
    network, auth), irreversibility (data migrations, schema changes),
    breadth (number of touched modules), and dangerous patterns (eval,
    raw HTML injection, regex on untrusted input, concurrency / async
    races, file/network I/O, telemetry definitions, mots.yaml /
    build / CI files).

  - COMPLEXITY: how hard the change is for a human reviewer to
    understand and verify. Considers LOC added/removed, number of
    files, control-flow density, new abstractions, refactors / renames,
    presence vs absence of tests, and clarity of the diff.

Both axes are independent. A simple 5-line patch to a security-critical
file is HIGH risk but LOW complexity.

Score anchors (use these as a calibration reference, do not be afraid
to score 0 or 1):

  RISK
    0  = pure docs / comments / strings, no executable code change
    1  = CSS-only, dead-code removal, isolated UI tweak in a leaf component,
         a localization string addition
    2  = small JS/HTML change in a non-sensitive UI component, no network
         or storage touched
    3-4 = moderate change to UI logic, or any touch of a moderately
         sensitive area (telemetry, prefs reads)
    5-6 = multi-file change with cross-cutting effects, or touches
         moderately sensitive subsystems
    7-8 = security-relevant code, IPC, sandbox, auth, crypto, network
         protocols, build / CI / signing
    9-10 = data migrations, irreversible schema changes, security boundary
         changes

  COMPLEXITY
    0  = whitespace, single-line value change, single-line string change
    1  = <10 LOC, single file, no control flow added
    2  = ~10-30 LOC, 1-2 files, simple straight-line additions
    3-4 = 30-100 LOC, new function/method, simple control flow
    5-6 = 100-300 LOC OR 5+ files OR new abstraction
    7-8 = significant refactor, renames, signature changes across many
         callers, or non-trivial concurrency/async logic
    9-10 = large refactors with subtle invariants, new subsystems

Return STRICT JSON only, no prose, matching exactly this schema:

{
  "risk": <int 0-10>,
  "risk_factors": ["<short sentence, cite file paths where relevant>", ...],
  "complexity": <int 0-10>,
  "complexity_factors": ["<short sentence>", ...]
}

Provide 1-5 factors per axis. Each factor MUST be ONE short sentence,
not a paragraph. Cite specific file paths in `path:line` form when
useful. Do NOT include any text outside the JSON object.
"""


class Scores(BaseModel):
    risk: int = Field(ge=0, le=10)
    complexity: int = Field(ge=0, le=10)
    risk_factors: list[str] = Field(default_factory=list)
    complexity_factors: list[str] = Field(default_factory=list)


@dataclass
class ScoringResult:
    scores: Scores
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw_text: str = ""


def _build_user_message(
    *,
    title: str,
    summary: str,
    revision_id: int,
    author_phid: str,
    bug_id: str | None,
    raw_diff: str,
) -> str:
    header = (
        f"Revision: D{revision_id}\n"
        f"Title: {title}\n"
        f"Author: {author_phid}\n"
        f"Bug: {bug_id or '(none)'}\n"
        f"\nSummary:\n{summary or '(no summary provided)'}\n"
    )
    return f"{header}\n----- BEGIN DIFF -----\n{raw_diff}\n----- END DIFF -----\n"


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json … ``` fences if Claude wrapped the JSON.
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match:
            return json.loads(match.group(0))
        raise


def score_revision(
    client: Anthropic,
    *,
    model: str,
    max_tokens: int,
    title: str,
    summary: str,
    revision_id: int,
    author_phid: str,
    bug_id: str | None,
    raw_diff: str,
) -> ScoringResult:
    """Call Claude to compute scores. Raises on Claude or parse failure."""
    user_msg = _build_user_message(
        title=title,
        summary=summary,
        revision_id=revision_id,
        author_phid=author_phid,
        bug_id=bug_id,
        raw_diff=raw_diff,
    )
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": SCORING_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    text_parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    raw_text = "".join(text_parts)
    try:
        parsed = _extract_json(raw_text)
        scores = Scores.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as e:
        log.error("scoring response was not valid JSON: %s\n---\n%s", e, raw_text[:1000])
        raise

    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0)
        or 0,
    }

    return ScoringResult(scores=scores, model=model, usage=usage, raw_text=raw_text)
