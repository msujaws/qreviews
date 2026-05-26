const STEPS: Array<{ label: string; body: string }> = [
  {
    label: "discover",
    body: "Poll Phabricator for revisions tagged with the configured reviewer groups.",
  },
  {
    label: "score",
    body: "Ask Claude (Haiku) to rate risk and complexity on a 0–10 scale, with factors cited.",
  },
  {
    label: "gate",
    body: "Proceed only when both scores fall below the group's threshold. Otherwise, skip.",
  },
  {
    label: "review",
    body: "Run a multi-turn Claude review using the group's SKILL.md, with searchfox tools for cross-references.",
  },
  {
    label: "post",
    body: "Render a single advisory comment via Conduit. Never accept, reject, or request changes.",
  },
  {
    label: "track",
    body: "Persist every step to SQLite so this dashboard can show throughput, distributions, and per-revision detail.",
  },
];

const SOURCE_URL = "https://github.com/msujaws/qreviews";
const ROADMAP_URL = `${SOURCE_URL}#long-term-vision`;
const NEXT_STEPS_URL = `${SOURCE_URL}#next-steps`;

export function HowItWorks() {
  const linkCls =
    "text-[var(--pt-flame)] border-b border-dotted border-[rgba(255,106,61,0.6)] hover:border-[var(--pt-flame)] transition-colors";
  return (
    <div className="flex flex-col gap-8 pt-surface px-8 py-7">
      <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)] max-w-[78ch]">
        Every revision flows through the same six-step pipeline: discover,
        score, gate, review, post, track. The bot is strictly{" "}
        <strong>non-blocking</strong> — the only Phabricator write it ever
        emits is a{" "}
        <code className="pt-mono text-[13px] text-[var(--pt-flame)]">comment</code>{" "}
        transaction. No accept, no reject, no request-changes.
      </p>

      <ol className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-[var(--pt-hairline)] border border-[var(--pt-hairline)]">
        {STEPS.map((step, idx) => (
          <li
            key={step.label}
            className="flex flex-col gap-2 px-5 py-5 bg-[var(--pt-surface)]"
          >
            <div className="flex items-baseline gap-3">
              <span className="pt-mono text-[11px] text-[var(--pt-muted)] tracking-[0.18em]">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <span className="pt-eyebrow">{step.label}</span>
            </div>
            <div className="text-[13.5px] leading-[1.6] text-[var(--pt-ink)]">
              {step.body}
            </div>
          </li>
        ))}
      </ol>

      <div className="pt-mono text-[12px] text-[var(--pt-muted)] leading-[1.7]">
        below: throughput and score histograms across all observed revisions,
        followed by the recent-activity ledger. Click any row to see the full
        posted comment, factors, token usage, and a link to Phabricator.
        <span className="mx-2 text-[var(--pt-hairline)]">·</span>
        <a href={ROADMAP_URL} target="_blank" rel="noreferrer" className={linkCls}>
          roadmap ↗
        </a>
        <span className="mx-2 text-[var(--pt-hairline)]">·</span>
        <a href={NEXT_STEPS_URL} target="_blank" rel="noreferrer" className={linkCls}>
          next steps ↗
        </a>
        <span className="mx-2 text-[var(--pt-hairline)]">·</span>
        <a href={SOURCE_URL} target="_blank" rel="noreferrer" className={linkCls}>
          source on github ↗
        </a>
      </div>
    </div>
  );
}
