import { Collapse } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { PipelineDiagram } from "./PipelineDiagram";

const PROBLEMS: Array<{ label: string; body: string }> = [
  {
    label: "Slow queue",
    body: "Patches sit unreviewed for days, even the routine ones.",
  },
  {
    label: "Lost attention",
    body: "Reviewers spend their attention on a steady stream of small, low-risk changes. The patches that need careful eyes get less of it.",
  },
  {
    label: "Routine load",
    body: "Most revisions in these queues are small and repetitive. They consume reviewer time before the harder patches get attention.",
  },
  {
    label: "Fresh-eyes gap",
    body: "Routine patches rarely get a careful second pass. Reviewers save their focus for the harder ones.",
  },
];

const STEPS: Array<{ label: string; body: string }> = [
  {
    label: "Discover",
    body: "Poll Phabricator for revisions tagged with configured reviewer groups.",
  },
  {
    label: "Score",
    body: "Ask Claude (Haiku) to rate risk and complexity on a 0–10 scale, with factors cited.",
  },
  {
    label: "Gate",
    body: "Proceed only when both scores fall below the group's threshold. Otherwise, skip.",
  },
  {
    label: "Review",
    body: "Run a multi-turn Claude review using the group's SKILL.md, with searchfox tools for cross-references.",
  },
  {
    label: "Post",
    body: "Render a single advisory comment via Conduit. Never accept, reject, or request changes.",
  },
  {
    label: "Track",
    body: "Persist every step to SQLite so this dashboard can show throughput, distributions, and per-revision detail.",
  },
];

const SOURCE_URL = "https://github.com/msujaws/qreviews";
const ROADMAP_URL = `${SOURCE_URL}#long-term-vision`;
const NEXT_STEPS_URL = `${SOURCE_URL}#next-steps`;

export function WhyAndHow() {
  const [opened, { toggle }] = useDisclosure(true);
  const linkCls = "pt-link";

  return (
    <section className="flex flex-col gap-5">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={opened}
        aria-controls="why-and-how-body"
        className="pt-eyebrow pt-eyebrow--rule bg-transparent border-0 p-0 cursor-pointer text-left w-full"
      >
        <span aria-hidden="true" className="inline-block w-3 text-[var(--pt-muted)]">
          {opened ? "▾" : "▸"}
        </span>
        <span>Why and how</span>
      </button>

      <Collapse in={opened}>
        <div
          id="why-and-how-body"
          className="flex flex-col gap-8 pt-surface px-8 py-8"
        >
          <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)]">
            Firefox review queues keep hitting four patterns.
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

          <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)]">
            qreviews acts only on revisions that score low on both{" "}
            <strong>risk</strong> and <strong>complexity</strong>. It
            posts a non-binding advisory comment. A human reviewer still
            makes the formal accept or reject call. The goal is to clear
            the easy queue so reviewers can spend their attention on the
            patches that need it.
          </p>

          <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)] border-l-2 border-[var(--pt-flame)] pl-4">
            As the rubric improves and teams get comfortable, thresholds
            rise. The bot eventually opens up to revisions from outside
            the immediate review group. It never blocks, never accepts,
            never rejects.
          </p>

          <p className="text-[15px] leading-[1.7] text-[var(--pt-ink)]">
            Every revision flows through the same six-step pipeline:
            discover, score, gate, review, post, track. The bot is
            strictly <strong>non-blocking</strong>. The only Phabricator
            write it ever emits is a{" "}
            <code className="pt-mono text-[13px] text-[var(--pt-flame)]">
              comment
            </code>{" "}
            transaction. No accept, no reject, no request-changes.
          </p>

          <div className="flex flex-col gap-3">
            <div className="pt-eyebrow">Pipeline</div>
            <div className="border border-[var(--pt-hairline)] bg-[var(--pt-bg)] px-4 py-5">
              <PipelineDiagram />
            </div>
          </div>

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
            Throughput and score histograms across all observed revisions
            follow below, then the recent-activity ledger. Click any row
            for the full posted comment, factors, token usage, and a link
            to Phabricator.
            <span className="mx-2 text-[var(--pt-hairline)]">·</span>
            <a
              href={ROADMAP_URL}
              target="_blank"
              rel="noreferrer"
              className={linkCls}
            >
              Roadmap
            </a>
            <span className="mx-2 text-[var(--pt-hairline)]">·</span>
            <a
              href={NEXT_STEPS_URL}
              target="_blank"
              rel="noreferrer"
              className={linkCls}
            >
              Next steps
            </a>
            <span className="mx-2 text-[var(--pt-hairline)]">·</span>
            <a
              href={SOURCE_URL}
              target="_blank"
              rel="noreferrer"
              className={linkCls}
            >
              Source on GitHub
            </a>
          </div>
        </div>
      </Collapse>
    </section>
  );
}
