import { BarChart } from "@mantine/charts";
import type { Histograms } from "../types";
import { Eyebrow } from "./Eyebrow";

interface Props {
  data: Histograms | undefined;
  riskThreshold: number;
  complexityThreshold: number;
}

export function HistogramChart({ data, riskThreshold, complexityThreshold }: Props) {
  const rows = Array.from({ length: 11 }, (_, i) => ({
    score: i.toString(),
    risk: data?.risk[i] ?? 0,
    complexity: data?.complexity[i] ?? 0,
  }));

  const hasData = rows.some((r) => r.risk > 0 || r.complexity > 0);

  return (
    <section className="pt-surface px-6 py-6 flex flex-col gap-5 min-h-[280px]">
      <div className="flex items-baseline justify-between gap-4">
        <Eyebrow rule>score distribution</Eyebrow>
        <div className="pt-mono text-[11px] text-[var(--pt-muted)]">
          gate: r&lt;{riskThreshold} · c&lt;{complexityThreshold}
        </div>
      </div>
      {!hasData ? (
        <EmptyState />
      ) : (
        <BarChart
          h={220}
          data={rows}
          dataKey="score"
          withLegend
          legendProps={{ verticalAlign: "bottom", height: 24 }}
          gridAxis="y"
          gridColor="rgba(232, 236, 244, 0.06)"
          textColor="var(--pt-muted)"
          tickLine="none"
          series={[
            { name: "risk", color: "var(--pt-info)" },
            { name: "complexity", color: "var(--pt-flame)" },
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
      <span className="pt-mono text-[12px] text-[var(--pt-muted)]">no scores recorded yet</span>
    </div>
  );
}
