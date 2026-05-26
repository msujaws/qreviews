const PROBLEMS: Array<{ label: string; body: string }> = [
  {
    label: "bias worry",
    body: "Engineers worry opt-in AI review puts a thumb on the scale, and they're right to be skeptical.",
  },
  {
    label: "uneven opt-in",
    body: "A handful of power-users request AI review on every patch; most patches never get one.",
  },
  {
    label: "slow queue",
    body: "Patches sit unreviewed for days, even the routine ones.",
  },
  {
    label: "lost attention",
    body: "When reviewers are drowning in small, low-risk changes, the patches that need careful eyes get less scrutiny.",
  },
];

export function Premise() {
  return (
    <div className="flex flex-col gap-7 pt-surface px-8 py-7">
      <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)] max-w-[78ch]">
        Review queues for Firefox engineering teams — initially{" "}
        <strong>Home &amp; New Tab</strong> and{" "}
        <strong>IP Protection</strong> — keep hitting the same four
        failure modes:
      </p>

      <ul className="grid grid-cols-1 md:grid-cols-2 gap-px bg-[var(--pt-hairline)] border border-[var(--pt-hairline)]">
        {PROBLEMS.map((p) => (
          <li
            key={p.label}
            className="flex flex-col gap-2 px-5 py-5 bg-[var(--pt-surface)]"
          >
            <span className="pt-eyebrow">{p.label}</span>
            <span className="text-[13.5px] leading-[1.6] text-[var(--pt-ink)]">
              {p.body}
            </span>
          </li>
        ))}
      </ul>

      <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)] max-w-[78ch]">
        qreviews' answer is narrower than "AI reviews everything." It
        only acts on revisions that score low on both <strong>risk</strong>{" "}
        and <strong>complexity</strong>, posts a non-binding advisory
        comment, and leaves the formal accept/reject decision to a
        human. As the rubric improves and teams get comfortable, the
        thresholds rise and the bot opens up to revisions from outside
        the immediate review group. It never blocks, never accepts,
        never rejects.
      </p>

      <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)] max-w-[78ch] border-l-2 border-[var(--pt-flame)] pl-4">
        The goal is to clear the easy queue so reviewers can spend
        their attention on the hard stuff — not to replace human
        judgment.
      </p>
    </div>
  );
}
