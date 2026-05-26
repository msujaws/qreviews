"""Generate a Claude review of a revision using a skill + searchfox tool use.

The review model runs in a tool-use loop:

  1. Send: SKILL.md system prompt + revision metadata + diff + tools.
  2. Receive: a response that may contain tool_use blocks (read_file,
     find_definition, find_callers, find_callees, search_code).
  3. Execute each requested tool via `qreviews.searchfox` and append the
     tool_result blocks to the next request.
  4. Repeat until the response has `stop_reason == "end_turn"` (no more tool
     calls) or we hit the max-iterations cap.

Token usage is aggregated across all turns so the metrics dashboard reflects
the true cost.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic

from qreviews.searchfox import TOOL_SCHEMAS, execute_tool
from qreviews.skills import load_skill

log = logging.getLogger(__name__)


REVIEW_WRAPPER = """\
You are reviewing a Mozilla Firefox patch on Phabricator on behalf of an
overloaded human reviewer group. Below is durable, area-specific guidance you
must apply. The patch was already gated as LOW RISK and LOW COMPLEXITY, so
your review should focus on:

  - Concrete actionable findings (bugs, lint/style issues called out by the
    guidance, missed conventions). Be specific — quote the file and line.
  - Confirming what looks good. The bot's comment is posted publicly to the
    revision and is read by a human; explicit "this looks fine because …"
    helps the human ratify it quickly.
  - Cite all findings using the form `path/to/file.ext:LINE` so reviewers can
    jump to them.

You have searchfox tools that let you read any file in mozilla-central and
follow symbols. Use them BEFORE flagging something as a potential issue.
Specifically:

  - If you're about to say "X may not be defined", first call
    `find_definition` or `search_code` to check whether it actually exists.
  - If you're about to flag a signature/API change as risky, call
    `find_callers` to see who calls the affected symbol.
  - If you want to read more context around a changed line, call `read_file`
    with a line range — the diff alone often hides the surrounding shape.

You don't need to use the tools for every finding — only when verifying
something the diff alone can't answer. Aim for 0–5 tool calls per review;
more than that and you're probably exploring rather than reviewing.

Format your final output as GitHub-flavored Markdown suitable for posting as
a Phabricator comment. Use level-3 headings (###) for sections. Keep it under
500 words. Do NOT include scores, do NOT say "I approve" or "looks good to
land" — your job is to surface findings; the human approves.

Lead with a one-sentence overall summary, then a section of findings (or
"no findings" if appropriate), then a section listing what looks good.

----- BEGIN AREA REVIEW GUIDANCE -----

"""


MAX_TOOL_ITERATIONS = 8


@dataclass
class ReviewResult:
    body: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0


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


SUPPLEMENTAL_SKILLS_HEADER = (
    "\n\n---\n\n"
    "## Additional reviewer-group context\n\n"
    "This revision is also tagged with other reviewer groups whose "
    "rubrics are included below. Treat them as supplementary guidance "
    "alongside the primary area review guidance above; surface findings "
    "that any of them would care about.\n\n"
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
) -> ReviewResult:
    skill_body = load_skill(skill_path)
    system_text = REVIEW_WRAPPER + skill_body
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
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]

    aggregated_usage: dict[str, int] = {}
    tool_calls = 0

    tools_param: list[dict[str, Any]] | None = TOOL_SCHEMAS if enable_tools else None

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
            body = _final_text(response.content)
            return ReviewResult(
                body=body, model=model, usage=aggregated_usage, tool_calls=tool_calls
            )

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
    return ReviewResult(
        body=_final_text(response.content)
        or "(review exceeded tool iteration limit; no final answer produced)",
        model=model,
        usage=aggregated_usage,
        tool_calls=tool_calls,
    )
