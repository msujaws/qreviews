"""Generate a Claude review of a revision using a skill + searchfox tool use.

The review model runs in a tool-use loop:

  1. Send: structured system prompt (role + process + tool guidance +
     output format + examples + area-skill body) + revision metadata
     + diff + tools.
  2. Receive: a response that may contain tool_use blocks (read_file,
     find_definition, find_callers, find_callees, search_code).
  3. Execute each requested tool via `qreviews.searchfox` and append the
     tool_result blocks to the next request.
  4. Repeat until the response has `stop_reason == "end_turn"` (no more tool
     calls) or we hit the max-iterations cap.

The final turn is expected to be a single fenced JSON object naming the
inline findings and any remaining narrative summary; see
`REVIEW_OUTPUT_FORMAT` and `parse_review_payload` below. If the response
doesn't parse, we fall back to posting the raw text as summary-only.

Token usage is aggregated across all turns so the metrics dashboard reflects
the true cost.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic

from qreviews.json_utils import extract_json_object
from qreviews.searchfox import TOOL_SCHEMAS, execute_tool, has_searchfox
from qreviews.skills import load_skill

log = logging.getLogger(__name__)


REVIEW_ROLE = """\
You are reviewing a Mozilla Firefox patch on Phabricator on behalf of an
overloaded human reviewer group. The patch was already gated as LOW RISK
and LOW COMPLEXITY by a separate scoring pass — your job is to surface
concrete issues a human reviewer would want flagged, not to re-litigate
whether the patch should land at all. A human will read your review and
either ratify it or override it; you are advisory.

"""


REVIEW_PROCESS = """\
## Review process

Follow this systematic approach:

**Step 1 — Analyze the changes.** Read the patch summary for context,
then focus on the diff itself. Identify the intent and structure of
the changes. The pre-computed `<test_signals>` block in the user
message tells you whether the patch includes tests and whether
existing tests in the tree reference the touched files — incorporate
that into your judgement.

**Step 2 — Identify issues.** Look for bugs, logical errors,
performance problems, security vulnerabilities, and violations of
the area-specific guidance below. Focus ONLY on new or changed lines
(those that begin with `+`). Never comment on unmodified context
lines.

Prioritize issues in this order:
  Security vulnerabilities > Functional bugs > Performance issues >
  Style / readability concerns.

**Step 3 — Verify and assess confidence.** Use the available tools
when you need to verify a concern or gather additional context. Only
include a finding when you are at least 80% confident the issue is
valid. When in doubt, verify before flagging.

**Step 4 — Sort by confidence and importance.** Lead with the issues
you are most certain about and that matter most. Drop borderline
items rather than padding the review.

**Step 5 — Write clear, direct comments.** Use declarative language:
state the problem, then suggest the fix. Use directive verbs: "Fix",
"Remove", "Change", "Add". NEVER use these hedging phrases: "maybe",
"might want to", "consider", "possibly", "could be", "you may want
to". Each comment should be short and specific. The full voice rules
are codified in `docs/STYLE.md` and grounded in real Mozilla
bugzilla prose; match the example findings below.

## What NOT to include

Do not write findings that:
  - Refer to unmodified code (lines without a `+` prefix).
  - Ask for verification or confirmation (e.g. "Check if…", "Ensure
    that…").
  - Provide praise or restate obvious facts.
  - Flag style preferences without a clear coding-standard
    violation.
  - Recommend extracting a value into a constant, token, variable,
    or helper unless it is shared across call sites or a named
    abstraction already exists. Renaming a single-use literal is not
    an improvement.
  - Point out issues that the visible code already handles.

One exception: if the `<test_signals>` block reports
`coverage_signal=uncovered` AND the patch touches non-trivial logic,
it IS appropriate to surface "no test coverage on this change" as a
finding — that is a code-quality concern, not a generic testing
nit.

"""


REVIEW_TOOL_GUIDANCE = """\
## Tool use

You have searchfox tools that let you read any file in mozilla-central
and follow symbols. Use them BEFORE flagging something as a potential
issue:

  - About to say "X may not be defined"? Call `find_definition` or
    `search_code` to confirm.
  - About to flag a signature/API change as risky? Call
    `find_callers` to see who calls the affected symbol.
  - Want to see more context around a changed line? Call `read_file`
    with a line range.
  - The `<test_signals>` block reports `coverage_signal=partial` or
    `uncovered`? You may run a path-scoped `search_code` against
    `tests/`, `mochitest/`, `xpcshell/`, etc. to confirm before
    raising missing-coverage as a finding.

Aim for 0-5 tool calls per review. More than that and you're
exploring rather than reviewing.

"""


REVIEW_OUTPUT_FORMAT = """\
## Output format

End your response with a single fenced JSON object — no prose before
or after. The JSON object must match this exact schema:

```json
{
  "summary": "<markdown summary of the review; can be empty>",
  "findings": [
    {
      "file_path": "path/to/file.ext",
      "line": <integer line number>,
      "is_new_file": <true if `line` refers to the new (+) side, false if the old (-) side>,
      "body": "<the comment to post inline at this line>",
      "confidence": <float 0.0-1.0>
    }
  ]
}
```

Rules for the output:

  - Each finding's `(file_path, line, is_new_file)` MUST name a line
    that actually appears in a diff hunk. Inventing line numbers is
    worse than dropping the finding.
  - For findings about added or modified code, use `is_new_file:
    true` and the new-side line number.
  - Use `summary` ONLY for findings that genuinely cannot be pinned
    to a single line (e.g. "this commit lacks a corresponding test
    file"). If every finding fits inline, leave `summary` empty.
  - Do NOT include any praise, status statements, or "I approve"
    language in `summary`. Do NOT mention scores or risk levels.
  - If there are no findings, return an empty array and an empty
    summary string.

"""


REVIEW_EXAMPLES = """\
## Style examples (Mozilla code)

Three examples of well-formed inline findings. Match this voice —
declarative, no hedging.

**Example 1** (memory efficiency, C++):
file_path: netwerk/streamconv/converters/mozTXTToHTMLConv.cpp
line: 1211
body: `nsAutoStringN<256>` has a fixed size. Confirm `tempString`
cannot exceed 256 characters before assuming the small-buffer
optimization holds.

**Example 2** (performance, JS):
file_path: toolkit/components/extensions/ExtensionDNR.sys.mjs
line: 1837
body: `filterAAR` is recreated on every call to
`#updateAllowAllRequestRules`. Move the definition out of the
method so it's allocated once.

**Example 3** (readability, JS):
file_path: devtools/shared/network-observer/NetworkUtils.sys.mjs
line: 496
body: Extract `!Components.isSuccessCode(status) &&
blockList.includes(ChromeUtils.getXPCOMErrorName(status))` into a
named helper like `isBlockedError(status)` to make the condition
self-describing.

"""


REVIEW_AREA_GUIDANCE_HEADER = "----- BEGIN AREA REVIEW GUIDANCE -----\n\n"

SUPPLEMENTAL_SKILLS_HEADER = (
    "\n\n---\n\n"
    "## Additional reviewer-group context\n\n"
    "This revision is also tagged with other reviewer groups whose "
    "rubrics are included below. Treat them as supplementary guidance "
    "alongside the primary area review guidance above; surface findings "
    "that any of them would care about.\n\n"
)


MAX_TOOL_ITERATIONS = 8


@dataclass
class Finding:
    file_path: str
    line: int
    is_new_file: bool
    body: str
    confidence: float = 0.0


@dataclass
class ReviewResult:
    summary: str
    findings: list[Finding] = field(default_factory=list)
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0
    # True when we couldn't parse a structured JSON object out of
    # the final response. The caller then posts `summary` (which is
    # the raw text) as a summary-only comment.
    parse_failed: bool = False
    # Findings the model named but that didn't match a legal diff
    # anchor; their bodies were appended to `summary`.
    rejected_count: int = 0


def _build_user_message(
    *,
    title: str,
    summary: str,
    revision_id: int,
    author_phid: str,
    bug_id: str | None,
    raw_diff: str,
    test_signals_block: str | None = None,
) -> str:
    header = (
        f"Revision: D{revision_id}\n"
        f"Title: {title}\n"
        f"Author: {author_phid}\n"
        f"Bug: {bug_id or '(none)'}\n"
        f"\nSummary:\n{summary or '(no summary provided)'}\n"
    )
    signals = f"\n{test_signals_block}\n" if test_signals_block else ""
    return (
        f"{header}{signals}\n----- BEGIN DIFF -----\n"
        f"{raw_diff}\n----- END DIFF -----\n"
    )


def _add_usage(into: dict[str, int], response_usage) -> None:
    into["input_tokens"] = into.get("input_tokens", 0) + getattr(
        response_usage, "input_tokens", 0
    )
    into["output_tokens"] = into.get("output_tokens", 0) + getattr(
        response_usage, "output_tokens", 0
    )
    into["cache_read_input_tokens"] = into.get("cache_read_input_tokens", 0) + (
        getattr(response_usage, "cache_read_input_tokens", 0) or 0
    )
    into["cache_creation_input_tokens"] = into.get("cache_creation_input_tokens", 0) + (
        getattr(response_usage, "cache_creation_input_tokens", 0) or 0
    )


def _final_text(content_blocks: list[Any]) -> str:
    parts = [b.text for b in content_blocks if getattr(b, "type", "") == "text"]
    return "".join(parts).strip()


def parse_review_payload(
    raw_text: str,
    *,
    legal_anchors: frozenset[tuple[str, int, bool]] | None = None,
) -> ReviewResult:
    """Parse Claude's final response into a structured ReviewResult.

    Falls back to summary-only (with `parse_failed=True`) when the text
    isn't a valid JSON object. When `legal_anchors` is provided, findings
    whose `(file_path, line, is_new_file)` triple isn't in the set are
    rejected and their `body` text is appended to the summary so nothing
    is silently lost.
    """
    try:
        payload = extract_json_object(raw_text)
    except json.JSONDecodeError:
        log.warning("review response was not parseable JSON; falling back to summary-only")
        return ReviewResult(summary=raw_text.strip(), parse_failed=True)

    summary = str(payload.get("summary") or "").strip()
    raw_findings = payload.get("findings") or []
    accepted: list[Finding] = []
    rejected_bodies: list[str] = []
    rejected_count = 0

    if not isinstance(raw_findings, list):
        log.warning("review payload.findings was not a list; ignoring")
        raw_findings = []

    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path") or "").strip()
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        is_new_file = bool(item.get("is_new_file", True))
        body = str(item.get("body") or "").strip()
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if not file_path or not body or line <= 0:
            continue

        anchor = (file_path, line, is_new_file)
        if legal_anchors is not None and anchor not in legal_anchors:
            rejected_count += 1
            rejected_bodies.append(f"- `{file_path}:{line}` — {body}")
            log.info("review finding rejected (no anchor): %s:%d new=%s", file_path, line, is_new_file)
            continue

        accepted.append(
            Finding(
                file_path=file_path,
                line=line,
                is_new_file=is_new_file,
                body=body,
                confidence=confidence,
            )
        )

    if rejected_bodies:
        appendix = (
            "\n\n_Findings that could not be anchored to a specific diff line:_\n"
            + "\n".join(rejected_bodies)
        )
        summary = (summary + appendix).strip()

    return ReviewResult(
        summary=summary,
        findings=accepted,
        rejected_count=rejected_count,
    )


def generate_review(
    client: Anthropic,
    *,
    model: str,
    max_tokens: int,
    skill_path: str,
    title: str,
    summary: str,
    revision_id: int,
    author_phid: str,
    bug_id: str | None,
    raw_diff: str,
    additional_skill_paths: Sequence[str] = (),
    max_iterations: int = MAX_TOOL_ITERATIONS,
    enable_tools: bool = True,
    test_signals_block: str | None = None,
    legal_anchors: frozenset[tuple[str, int, bool]] | None = None,
) -> ReviewResult:
    if enable_tools and not has_searchfox():
        log.warning(
            "searchfox-cli not found; reviewing D%d without tool use", revision_id
        )
        enable_tools = False

    skill_body = load_skill(skill_path)
    system_parts = [REVIEW_ROLE, REVIEW_PROCESS]
    if enable_tools:
        system_parts.append(REVIEW_TOOL_GUIDANCE)
    system_parts.extend([REVIEW_OUTPUT_FORMAT, REVIEW_EXAMPLES, REVIEW_AREA_GUIDANCE_HEADER, skill_body])
    system_text = "".join(system_parts)
    if additional_skill_paths:
        supplemental_bodies = [load_skill(p) for p in additional_skill_paths]
        system_text += SUPPLEMENTAL_SKILLS_HEADER + "\n\n---\n\n".join(supplemental_bodies)

    user_msg = _build_user_message(
        title=title,
        summary=summary,
        revision_id=revision_id,
        author_phid=author_phid,
        bug_id=bug_id,
        raw_diff=raw_diff,
        test_signals_block=test_signals_block,
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]

    aggregated_usage: dict[str, int] = {}
    tool_calls = 0

    tools_param: list[dict[str, Any]] | None = TOOL_SCHEMAS if enable_tools else None

    response = None
    for _iteration in range(max_iterations):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": messages,
        }
        if tools_param is not None:
            kwargs["tools"] = tools_param

        response = client.messages.create(**kwargs)
        _add_usage(aggregated_usage, response.usage)

        # Collect any tool_use blocks; if there are none, we're done.
        tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]

        if not tool_uses or response.stop_reason != "tool_use":
            result = parse_review_payload(
                _final_text(response.content),
                legal_anchors=legal_anchors,
            )
            result.model = model
            result.usage = aggregated_usage
            result.tool_calls = tool_calls
            return result

        # Append the assistant turn (with the tool_use blocks) and the tool results.
        messages.append(
            {
                "role": "assistant",
                "content": [b.model_dump() for b in response.content],
            }
        )

        tool_results = []
        for tu in tool_uses:
            tool_calls += 1
            log.info(
                "review tool call #%d: %s(%s)",
                tool_calls,
                tu.name,
                ", ".join(f"{k}={v!r}" for k, v in (tu.input or {}).items()),
            )
            result_text = execute_tool(tu.name, tu.input or {})
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_text,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    # Hit iteration cap — return what we have plus a note.
    log.warning("review hit max tool iterations (%d)", max_iterations)
    fallback_text = (
        _final_text(response.content)
        if response is not None
        else "(review exceeded tool iteration limit; no final answer produced)"
    )
    result = parse_review_payload(fallback_text, legal_anchors=legal_anchors)
    if not result.summary and not result.findings:
        result.summary = "(review exceeded tool iteration limit; no final answer produced)"
        result.parse_failed = True
    result.model = model
    result.usage = aggregated_usage
    result.tool_calls = tool_calls
    return result
