# qreviews writing style

This guide codifies the voice for qreviews — both the dashboard SPA
and the review comments posted to Phabricator. The style is grounded
in the prose Mozilla developers actually write in
bugzilla.mozilla.org. Mirror that voice; do not invent a new one.

## Source of truth

A sample of ~75 recent FIXED bug summaries and 12 substantive comment
threads pulled from `Firefox` and `Core` products on
bugzilla.mozilla.org. Specific patterns below cite real bug IDs so
the voice can be re-verified at any time.

## Voice

- **Direct and declarative.** State the problem, then the fix. Never
  use "consider", "maybe", "might want to", "could be", "appears to",
  "I think", "you may want to".
- **Active voice.** "The function returns null." Not "null is
  returned by the function."
- **Third-person impersonal.** Avoid first-person singular. Authorship
  is rarely interesting; describe the code or the behavior.
- **Present tense for explanation, past tense for actions taken.**
  ("`scrollIntoView` skips elements already in the viewport." /
  "Reverted because it caused node-test failures.")
- **No emoji. No exclamation points. No marketing language.**
- **No "please" / "thank you"** in technical content. Courtesy is
  expressed through clarity.

## Form

### Headings, labels, summaries

- **Sentence case fragments**, no terminal punctuation.
- Three shapes dominate Mozilla summaries:
  - **Declarative** ("X is broken / does Y"):
    - "Manage cookies and site data empty" (bug 2041077)
    - "Breach alert icon animation is displayed for old breaches"
      (bug 2039281)
    - "Text selection in PDFs is barely visible" (bug 1879559)
  - **Imperative** ("Add / Fix / Remove / Update X"):
    - "Add telemetry for the new Passwords and autofill pane"
      (bug 2041430)
    - "Drop support for PrivilegedAbout loading system principal
      shared workers" (bug 2042245)
    - "Update PDF.js to new version" (bug 2042211)
  - **Crash / diagnostic signature**:
    - "Crash in [@ mozilla::net::nsHttpConnectionMgr::CheckTransInPendingQueue]"
      (bug 2042389)
    - "Assertion failure: aParent.IsContent() && aParent.GetParent()"
      (bug 1884465)
- Length: 5–20 words typical; longer is fine when the precision
  warrants it (crash signatures, test paths).
- Metadata prefixes when useful: `[Nova]`, `[Intermittent]`, `Perma`,
  `Crash in [@ …]`. Use brackets, not parentheses.

### Body comments and prose

- **2–4 sentences for a substantive comment.** Drop borderline items
  rather than padding.
- **Cite code precisely**: backtick file paths
  (`browser/components/newtab/Foo.jsx`), `function()` with parens,
  full class paths (`mozilla::net::...`).
- **Cross-bug references** use lowercase "bug" + number:
  `bug 2040246`.
- **No praise, status statements, or approval language** in posted
  review bodies. The wrapper template carries any necessary framing.

## Anti-patterns

| Don't | Do |
|---|---|
| "Maybe you could consider extracting this into a helper." | "Extract `isBlockedError(status)` into a named helper." |
| "I think this might cause a regression." | "This regressed `foo()` in bug 2041391." |
| "🚀 Awesome work! LGTM!" | (omit — or: "No findings raised.") |
| "Please consider adding a test for this case." | "Add a test that covers `foo()` when `bar` is null." |
| "It seems like the function is being called multiple times." | "`filterAAR` is recreated on every call to `#updateAllowAllRequestRules`." |
| "the dashboard shows median risk · complex across all scored revisions" | "Median risk / complexity. Across all scored revisions." |

## Scope

This style applies to:

- **Dashboard SPA** — every user-facing string under
  `qreviews/dashboard/web/src/**`.
- **Posted comment template** — `qreviews/poster.py`
  (`COMMENT_TEMPLATE` and friends).
- **Review prompt voice** — the instructions in `qreviews/review.py`
  that direct the model. The existing `REVIEW_EXAMPLES` already
  match this guide; new examples should too.
- **Scoring prompt** — `qreviews/scoring.py` factor sentences.
- **Contributor docs** — `CLAUDE.md`, `README.md`, and anything else
  surfaced to a Mozilla audience.

Reviewer-area rubrics under `skills/*/SKILL.md` are scoped to
**technical content**. They inherit voice from the review prompt — do
not duplicate this guide into each skill file.

## Quick reference for reviewing a diff

Before posting a review comment, ask:

1. Does each finding state the problem directly, then the fix?
2. Are all hedging phrases gone ("maybe", "consider", "might",
   "could", "appears", "I think")?
3. Is every code reference backticked? Function names get parens.
4. Is each comment 4 sentences or shorter?
5. Is there any emoji, exclamation point, praise, or status
   language? If so, remove it.
