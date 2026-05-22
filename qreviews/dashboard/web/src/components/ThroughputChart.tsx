import { LineChart } from "@mantine/charts";
import type { TimeseriesPoint } from "../types";
import { Eyebrow } from "./Eyebrow";

interface Props {
  data: TimeseriesPoint[] | undefined;
}

export function ThroughputChart({ data }: Props) {
  const rows = (data ?? []).map((d) => ({
    date: d.date.slice(5), // MM-DD
    seen: d.seen,
    posted: d.posted,
  }));

  return (
    <section className="pt-surface px-6 py-6 flex flex-col gap-5 min-h-[280px]">
      <div className="flex items-baseline justify-between gap-4">
        <Eyebrow rule>daily throughput</Eyebrow>
        <div className="pt-mono text-[11px] text-[var(--pt-muted)]">last 30d</div>
      </div>
      {rows.length === 0 ? (
        <EmptyState />
      ) : (
        <LineChart
          h={220}
          data={rows}
          dataKey="date"
          withDots={false}
          withLegend
          legendProps={{ verticalAlign: "bottom", height: 24 }}
          curveType="monotone"
          strokeWidth={1.5}
          gridAxis="xy"
          gridColor="rgba(232, 236, 244, 0.06)"
          textColor="var(--pt-muted)"
          tickLine="none"
          series={[
            { name: "seen", color: "var(--pt-muted)" },
            { name: "posted", color: "var(--pt-flame)" },
          ]}
          tooltipProps={{
            wrapperStyle: { fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: 11 },
          }}
        />
      )}
    </section>
  );
}

function EmptyState() {
  return (
    <div className="h-[220px] pt-grid-dotted flex items-center justify-center">
      <span className="pt-mono text-[12px] text-[var(--pt-muted)]">no throughput data yet</span>
    </div>
  );
}
