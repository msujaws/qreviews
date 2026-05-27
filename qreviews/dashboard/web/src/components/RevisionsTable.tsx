import type { RevisionDetail } from "../types";
import { ScoreBadge } from "./ScoreBadge";
import { StatusPill } from "./StatusPill";
import { Eyebrow } from "./Eyebrow";

interface Props {
  rows: RevisionDetail[] | undefined;
  riskThreshold: number;
  complexityThreshold: number;
  onOpen: (revisionId: number) => void;
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${Number(n).toFixed(2)}`;
}

function TestPill({
  inDiff,
  coverage,
}: {
  inDiff: string | null;
  coverage: string | null;
}) {
  // Render the worst-news signal that's most useful for triage: an
  // "uncovered" change with no in-diff tests is the cell that should
  // pop out. Tests-only or covered-with-tests is reassuring.
  const labels: { text: string; tone: "warn" | "ok" | "muted" }[] = [];
  if (inDiff === "absent") {
    labels.push({ text: "no tests", tone: "warn" });
  } else if (inDiff === "tests_only") {
    labels.push({ text: "tests only", tone: "ok" });
  } else if (inDiff === "adequate") {
    labels.push({ text: "+tests", tone: "ok" });
  } else if (inDiff === "sparse") {
    labels.push({ text: "few tests", tone: "muted" });
  }
  if (coverage === "uncovered") {
    labels.push({ text: "uncovered", tone: "warn" });
  } else if (coverage === "covered") {
    labels.push({ text: "covered", tone: "ok" });
  } else if (coverage === "partial") {
    labels.push({ text: "partial", tone: "muted" });
  }
  if (labels.length === 0) {
    return <span className="text-[var(--pt-muted)]">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {labels.map((l, i) => (
        <span
          key={i}
          className={
            l.tone === "warn"
              ? "px-1.5 py-0.5 text-[10px] uppercase tracking-[0.1em] text-[var(--pt-flame)] border border-[var(--pt-flame)]/40 rounded-sm"
              : l.tone === "ok"
              ? "px-1.5 py-0.5 text-[10px] uppercase tracking-[0.1em] text-[var(--pt-ink)] border border-[var(--pt-hairline)] rounded-sm"
              : "px-1.5 py-0.5 text-[10px] uppercase tracking-[0.1em] text-[var(--pt-muted)] border border-[var(--pt-hairline)] rounded-sm"
          }
        >
          {l.text}
        </span>
      ))}
    </div>
  );
}

export function RevisionsTable({
  rows,
  riskThreshold,
  complexityThreshold,
  onOpen,
}: Props) {
  const data = rows ?? [];

  return (
    <section className="pt-surface flex flex-col">
      <div className="px-6 py-5 flex items-baseline justify-between border-b border-[var(--pt-hairline)]">
        <Eyebrow>recent revisions</Eyebrow>
        <span className="pt-mono text-[11px] text-[var(--pt-muted)]">
          click row · details &gt;
        </span>
      </div>

      {data.length === 0 ? (
        <div className="px-6 py-16 pt-grid-dotted">
          <div className="pt-mono text-[12px] text-[var(--pt-muted)] text-center">
            no revisions yet — the poller hasn't recorded anything.
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm pt-mono">
            <thead>
              <tr className="text-[10px] uppercase tracking-[0.14em] text-[var(--pt-muted)]">
                <th className="px-6 py-3 text-left font-medium">revision</th>
                <th className="px-6 py-3 text-left font-medium">group</th>
                <th className="px-6 py-3 text-left font-medium" style={{ fontFamily: "'IBM Plex Sans', sans-serif" }}>title</th>
                <th className="px-3 py-3 text-right font-medium">risk</th>
                <th className="px-3 py-3 text-right font-medium">complex</th>
                <th className="px-3 py-3 text-left font-medium">tests</th>
                <th className="px-3 py-3 text-right font-medium">inlines</th>
                <th className="px-6 py-3 text-left font-medium">status</th>
                <th className="px-6 py-3 text-right font-medium">cost</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr
                  key={`${r.revision_id}-${r.diff_id ?? 0}`}
                  className="border-t border-[var(--pt-hairline)] cursor-pointer transition-colors hover:bg-[var(--pt-surface-raised)]"
                  onClick={() => onOpen(r.revision_id)}
                >
                  <td className="px-6 py-3 text-[var(--pt-flame)]">D{r.revision_id}</td>
                  <td className="px-6 py-3 text-[var(--pt-muted)]">{r.group_slug || "—"}</td>
                  <td
                    className="px-6 py-3 text-[var(--pt-ink)] truncate max-w-[420px]"
                    style={{ fontFamily: "'IBM Plex Sans', sans-serif" }}
                  >
                    {r.title || "—"}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <ScoreBadge value={r.risk} threshold={riskThreshold} />
                  </td>
                  <td className="px-3 py-3 text-right">
                    <ScoreBadge value={r.complexity} threshold={complexityThreshold} />
                  </td>
                  <td className="px-3 py-3 text-left">
                    <TestPill
                      inDiff={r.in_diff_test_signal}
                      coverage={r.coverage_signal}
                    />
                  </td>
                  <td className="px-3 py-3 text-right text-[var(--pt-muted)]">
                    {r.inline_count || 0}
                  </td>
                  <td className="px-6 py-3">
                    <StatusPill row={r} />
                  </td>
                  <td className="px-6 py-3 text-right text-[var(--pt-muted)]">
                    {fmtMoney(r.estimated_cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
