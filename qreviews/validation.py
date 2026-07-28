"""Deterministic checks on review output before anything is posted.

The bot is unattended and its output is public, so a malformed review has
to be suppressed rather than published and retracted. This module is the
first of two gates (`qreviews.critic` is the second). It is pure — no
network, no model calls — which is what makes the false-positive
behaviour exhaustively testable.

Four response tiers, ordered by how much they cost:

  A. Reject the whole post. Structural failures: an unparseable
     response, two competing payloads, a leaked JSON payload, leaked
     prompt scaffolding, verdict language, first-person chain of
     thought.
  B. Clear the summary, keep the inline findings. `summary` is optional
     by design, so dropping it is nearly free.
  C. Drop the one finding. Low confidence, hedged prose, over-length.
  D. Sanitize silently. Emoji and stray fence markers.

Two asymmetries worth remembering:

  - Leak checks run on raw text, because a leaked payload lives *inside*
    a fence. Voice checks run on code-stripped text, so
    `shouldConsider` and `if (!x)` don't read as hedging and
    punctuation.
  - `validate_rendered_body` deliberately skips the verdict check. The
    wrapper's own footer says "does not accept, reject, or request
    changes", and the model-authored parts were already checked
    individually before rendering.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from qreviews.review import Finding, ReviewResult

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ patterns

# Tier A — run against raw (un-stripped) text.

_LEAKED_PAYLOAD = re.compile(r"```(?:json)?\s*\{.*?\"findings\"", re.DOTALL)

# One stray key could plausibly appear in a quoted Firefox JSON blob, so
# require two distinct schema keys before calling it a leaked payload.
_SCHEMA_KEY = re.compile(r"\"(summary|findings|file_path|is_new_file|confidence)\"\s*:")

# Sourced from the literal prompt strings in qreviews/review.py: the
# guidance header, the diff delimiters, and the step headings. `[ \t]*`
# rather than `\s*` so the alternation can't span lines.
_SCAFFOLDING = re.compile(
    r"^-{3,}[ \t]*(?:BEGIN|END)\b"
    r"|BEGIN AREA REVIEW GUIDANCE"
    r"|END DIFF"
    r"|^## Review process[ \t]*$"
    r"|^\*\*Step \d",
    re.MULTILINE,
)

# An advisory bot emitting `r+` on mozilla-central misrepresents its own
# authority. That is a correctness problem, not a style nit. The `r[+-]`
# lookarounds keep C++ `r-value` from matching; bare "approved" is
# excluded because its adjectival use ("the approved origins list") is
# the common legitimate one.
_VERDICT = re.compile(
    r"(?<![\w-])r[+-](?![\w-])"
    r"|\bapprov(?:e|es|ing)\b"
    r"|request(?:ing)? changes",
    re.IGNORECASE,
)

# First-person and self-correction: the highest-signal chain-of-thought
# tells. `(?!/O)` keeps `I/O` from matching. Bare "wait" is excluded —
# "must wait for the promise" is ordinary prose.
_THINKING = re.compile(
    r"\bI\b(?!/O)"
    r"|\bmy\b"
    r"|let me (?:re-?check|reconsider|look|verify)"
    r"|on second thought"
    r"|scratch that"
    r"|wait[,—-]\s*let me",
    re.IGNORECASE,
)

# Tier B/C — run against code-stripped text only.

# Phrases, not bare modals: `could` and `might` are too common in
# legitimate declarative prose to be worth the recall.
_HEDGING = re.compile(
    r"\bmaybe\b"
    r"|\bperhaps\b"
    r"|\bpossibly\b"
    r"|might want to"
    r"|may want to"
    r"|\bconsider\b"
    r"|appears to"
    r"|seems? (?:to|like)"
    r"|I think"
    r"|could be",
    re.IGNORECASE,
)

_PRAISE = re.compile(
    r"\bLGTM\b|looks good|nice work|great job|well done|good catch",
    re.IGNORECASE,
)

_SCORE_TALK = re.compile(r"\brisk\b|\bcomplexity\b|/10", re.IGNORECASE)

_EXCLAMATION = re.compile(r"!")

# Tier D.

_EMOJI = re.compile(
    "["
    "\U0001f000-\U0001faff"  # pictographs, emoticons, transport, symbols
    "☀-➿"  # misc symbols and dingbats
    "️"  # variation selector-16
    "‍"  # zero-width joiner
    "]"
)

_STRAY_FENCE = re.compile(r"^[ \t]*```(?:json)?[ \t]*$", re.MULTILINE)

_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


# ------------------------------------------------------------------- results


@dataclass(frozen=True)
class Rejection:
    """One failed check. `code` becomes the recorded skip reason."""

    code: str
    scope: str  # "summary" | "body" | "finding[N] path:line"
    detail: str

    def __str__(self) -> str:
        return f"{self.code} ({self.scope}): {self.detail}"


@dataclass
class ValidationOutcome:
    summary: str
    findings: list[Finding] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    dropped: list[Rejection] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejections

    @property
    def skip_reason(self) -> str | None:
        if not self.rejections:
            return None
        return f"validation_{self.rejections[0].code}"

    def detail(self) -> dict[str, list[str]]:
        """Serializable record of what fired, for the skip event."""
        return {
            "rejections": [str(r) for r in self.rejections],
            "dropped": [str(r) for r in self.dropped],
        }


# ------------------------------------------------------------------- helpers


def _strip_code(text: str) -> str:
    """Remove fenced blocks and inline code spans.

    Voice checks run against this so identifiers and code fragments can't
    trip the prose patterns.
    """
    return _INLINE_CODE.sub(" ", _FENCED_BLOCK.sub(" ", text))


def _excerpt(text: str, match: re.Match[str], radius: int = 40) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end].replace("\n", " ").strip()


def _sanitize(text: str) -> str:
    """Tier D: lossless cleanup. No reason to suppress a good review over
    one emoji."""
    text = _EMOJI.sub("", text)
    text = _STRAY_FENCE.sub("", text)
    return text.strip()


def _leak_rejections(text: str, scope: str) -> list[Rejection]:
    """Tier A leak checks. Raw text — a leaked payload lives in a fence."""
    out: list[Rejection] = []
    m = _LEAKED_PAYLOAD.search(text)
    if m:
        out.append(Rejection("leaked_payload", scope, _excerpt(text, m)))
    keys = {m.group(1) for m in _SCHEMA_KEY.finditer(text)}
    if len(keys) >= 2:
        out.append(
            Rejection("leaked_schema_keys", scope, ", ".join(sorted(keys)))
        )
    m = _SCAFFOLDING.search(text)
    if m:
        out.append(Rejection("leaked_scaffolding", scope, _excerpt(text, m)))
    return out


def _voice_rejections(text: str, scope: str, *, max_chars: int) -> list[Rejection]:
    """Tier B/C checks. The caller decides whether these clear the summary
    or drop the single finding; neither suppresses the whole post."""
    out: list[Rejection] = []
    stripped = _strip_code(text)
    checks = (
        ("hedging", _HEDGING),
        ("praise", _PRAISE),
        ("exclamation", _EXCLAMATION),
    )
    for code, pattern in checks:
        m = pattern.search(stripped)
        if m:
            out.append(Rejection(code, scope, _excerpt(stripped, m)))
    if len(text) > max_chars:
        out.append(
            Rejection("too_long", scope, f"{len(text)} chars exceeds {max_chars}")
        )
    return out


# -------------------------------------------------------------------- public


def validate_review(
    review: ReviewResult,
    *,
    min_confidence: float,
    max_summary_chars: int,
    max_finding_chars: int,
) -> ValidationOutcome:
    """Gate a generated review. `outcome.ok is False` means post nothing."""
    rejections: list[Rejection] = []
    dropped: list[Rejection] = []

    # Tier A — whole-post structural failures.
    if review.parse_failed:
        rejections.append(
            Rejection(
                "parse_failed",
                "summary",
                "no schema-shaped JSON payload in the response",
            )
        )
    if review.payload_candidates > 1:
        rejections.append(
            Rejection(
                "ambiguous_payloads",
                "summary",
                f"{review.payload_candidates} competing payloads in the response",
            )
        )

    # Leak checks see the text before tier-D sanitizing, which would strip
    # the very fence markers a leaked payload is wrapped in.
    rejections.extend(_leak_rejections(review.summary, "summary"))
    summary = _sanitize(review.summary)
    stripped_summary = _strip_code(summary)
    for code, pattern in (("verdict_language", _VERDICT), ("leaked_thinking", _THINKING)):
        m = pattern.search(stripped_summary)
        if m:
            rejections.append(Rejection(code, "summary", _excerpt(stripped_summary, m)))

    findings: list[Finding] = []
    for index, finding in enumerate(review.findings):
        scope = f"finding[{index}] {finding.file_path}:{finding.line}"
        structural = _leak_rejections(finding.body, scope)
        body = _sanitize(finding.body)
        m = _VERDICT.search(_strip_code(body))
        if m:
            structural.append(
                Rejection("verdict_language", scope, _excerpt(_strip_code(body), m))
            )
        if structural:
            rejections.extend(structural)
            continue

        # Tier C — drop this finding, keep its siblings.
        if finding.confidence < min_confidence:
            dropped.append(
                Rejection(
                    "low_confidence",
                    scope,
                    f"confidence {finding.confidence} below {min_confidence}",
                )
            )
            continue
        if not body:
            dropped.append(Rejection("empty_body", scope, "body is empty"))
            continue
        voice = _voice_rejections(body, scope, max_chars=max_finding_chars)
        if voice:
            dropped.extend(voice)
            continue

        findings.append(
            Finding(
                file_path=finding.file_path,
                line=finding.line,
                is_new_file=finding.is_new_file,
                body=body,
                confidence=finding.confidence,
            )
        )

    # Tier B — clear the summary, keep the inlines.
    if summary:
        summary_voice = _voice_rejections(
            summary, "summary", max_chars=max_summary_chars
        )
        m = _SCORE_TALK.search(stripped_summary)
        if m:
            summary_voice.append(
                Rejection("restates_scores", "summary", _excerpt(stripped_summary, m))
            )
        if summary_voice:
            dropped.extend(summary_voice)
            summary = ""

    for r in dropped:
        log.info("validation dropped: %s", r)
    for r in rejections:
        log.warning("validation rejected: %s", r)

    return ValidationOutcome(
        summary=summary,
        findings=findings,
        rejections=rejections,
        dropped=dropped,
    )


def validate_rendered_body(body: str, *, max_chars: int) -> list[Rejection]:
    """Belt-and-braces check on the fully rendered comment.

    Leaks, length, and emoji only — the verdict and voice checks would
    fire on the wrapper's own copy. A rejection here means our template
    misbehaved, so callers should log at ERROR.
    """
    out = _leak_rejections(body, "body")
    if len(body) > max_chars:
        out.append(
            Rejection("too_long", "body", f"{len(body)} chars exceeds {max_chars}")
        )
    m = _EMOJI.search(body)
    if m:
        out.append(Rejection("emoji", "body", _excerpt(body, m)))
    return out
