import type { Summary } from "../types";
import { Eyebrow } from "./Eyebrow";

interface Props {
  summary: Summary | undefined;
}

function fmt(n: number | null | undefined, suffix = ""): string {
  if (n == null) return "—";
  return `${Number(n).toLocaleString()}${suffix}`;
}

function fmtPair(a: number | null | undefined, b: number | null | undefined): string {
  const left = a == null ? "—" : Math.round(a).toString();
  const right = b == null ? "—" : Math.round(b).toString();
  return `${left}/${right}`;
}

function fmtHours(n: number | null | undefined): { value: string; caption: string } {
  if (n == null || n <= 0) return { value: "0h", caption: "No advisory comments posted yet" };
  if (n < 1) {
    const minutes = Math.round(n * 60);
    return { value: `${minutes}m`, caption: "Reviewer time pre-empted" };
  }
  if (n < 10) {
    return { value: `${n.toFixed(1)}h`, caption: "Reviewer time pre-empted" };
  }
  if (n < 80) {
    return { value: `${Math.round(n)}h`, caption: "Reviewer time pre-empted" };
  }
  const days = (n / 8).toFixed(1);
  return { value: `${days}d`, caption: "Reviewer time pre-empted (8h/day)" };
}

interface CellProps {
  label: string;
  value: string;
  caption: string;
  highlight?: boolean;
}

function Cell({ label, value, caption, highlight = false }: CellProps) {
  return (
    <div className="flex flex-col gap-3 px-6 py-7 pt-surface">
      <Eyebrow rule>{label}</Eyebrow>
      <div
        className="pt-numeral pt-numeral--display"
        style={{
          fontSize: "clamp(54px, 6vw, 84px)",
          color: highlight ? "var(--pt-flame)" : "var(--pt-ink)",
        }}
      >
        {value}
      </div>
      <div className="pt-mono text-[11px] text-[var(--pt-muted)] tracking-wide">{caption}</div>
    </div>
  );
}

export function KpiRow({ summary }: Props) {
  const timeSaved = fmtHours(summary?.time_saved_hours);
  return (
    <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-px bg-[var(--pt-hairline)] border border-[var(--pt-hairline)]">
      <Cell
        label="Revisions seen"
        value={fmt(summary?.revisions_seen)}
        caption="Total observed by the bot"
      />
      <Cell
        label="Auto-reviewed"
        value={fmt(summary?.revisions_posted)}
        caption={`${summary?.coverage_pct ?? 0}% coverage`}
      />
      <Cell
        label="Median risk / complexity"
        value={fmtPair(summary?.median_risk, summary?.median_complexity)}
        caption="Across all scored revisions"
      />
      <Cell
        label="Reviewer time saved"
        value={timeSaved.value}
        caption={timeSaved.caption}
        highlight
      />
    </section>
  );
}
