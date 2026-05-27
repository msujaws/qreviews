import { Header } from "./components/Header";
import { KpiRow } from "./components/KpiRow";
import { ThroughputChart } from "./components/ThroughputChart";
import { HistogramChart } from "./components/HistogramChart";
import { RevisionsTable } from "./components/RevisionsTable";
import { RevisionDrawer } from "./components/RevisionDrawer";
import { Eyebrow } from "./components/Eyebrow";
import { WhyAndHow } from "./components/WhyAndHow";
import { useDashboardData } from "./hooks/useDashboardData";
import { useGroupParam } from "./hooks/useGroupParam";
import { useRevisionParam } from "./hooks/useRevisionParam";

const DEFAULT_RISK = 3;
const DEFAULT_COMPLEXITY = 3;

export function App() {
  const [group, setGroup] = useGroupParam();
  const [openRevision, setOpenRevision] = useRevisionParam();

  const { groups, summary, histograms, timeseries, revisions } = useDashboardData(group);

  const selectedGroupConfig = groups.data?.find((g) => g.slug === group);
  const riskThreshold = selectedGroupConfig?.risk_threshold ?? DEFAULT_RISK;
  const complexityThreshold = selectedGroupConfig?.complexity_threshold ?? DEFAULT_COMPLEXITY;

  return (
    <div className="min-h-screen pb-24">
      <Header groups={groups.data} selected={group} onChange={setGroup} />

      <main className="mx-auto max-w-[1280px] px-8 py-12 flex flex-col gap-16">
        <SectionWrap label="overview · summary">
          <KpiRow summary={summary.data} />
        </SectionWrap>

        <WhyAndHow />

        <SectionWrap label="signal · over time">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ThroughputChart data={timeseries.data} />
            <HistogramChart
              data={histograms.data}
              riskThreshold={riskThreshold}
              complexityThreshold={complexityThreshold}
            />
          </div>
        </SectionWrap>

        <SectionWrap label="ledger · recent activity">
          <RevisionsTable
            rows={revisions.data}
            riskThreshold={riskThreshold}
            complexityThreshold={complexityThreshold}
            onOpen={setOpenRevision}
          />
        </SectionWrap>

        <Footer />
      </main>

      <RevisionDrawer
        revisionId={openRevision}
        riskThreshold={riskThreshold}
        complexityThreshold={complexityThreshold}
        onClose={() => setOpenRevision(null)}
      />
    </div>
  );
}

function SectionWrap({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-5">
      <Eyebrow rule>{label}</Eyebrow>
      {children}
    </section>
  );
}

function Footer() {
  const linkCls =
    "text-[var(--pt-ink)] hover:text-[var(--pt-flame)] transition-colors border-b border-dotted border-[var(--pt-hairline)] hover:border-[var(--pt-flame)]";
  return (
    <footer className="mt-12 pt-8 border-t border-[var(--pt-hairline)] flex flex-col gap-3">
      <div className="pt-mono text-[11px] text-[var(--pt-muted)] tracking-[0.06em]">
        unofficial · not an official mozilla product
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-baseline sm:justify-between gap-y-3">
      <div className="pt-mono text-[11px] text-[var(--pt-muted)] tracking-[0.06em]">
        polling · sqlite · wal · refreshes hourly
      </div>
      <div className="pt-mono text-[11px] text-[var(--pt-muted)] tracking-[0.06em]">
        created with <span style={{ color: "var(--pt-flame)" }}>♥</span> by Jared Wein
        <span className="mx-2 text-[var(--pt-hairline)]">·</span>
        <a href="https://github.com/msujaws" target="_blank" rel="noreferrer" className={linkCls}>
          @jaws
        </a>
        <span className="mx-2 text-[var(--pt-hairline)]">·</span>
        <a
          href="https://github.com/msujaws/qreviews"
          target="_blank"
          rel="noreferrer"
          className={linkCls}
        >
          source ↗
        </a>
      </div>
      <div className="pt-mono text-[10px] text-[var(--pt-muted)] uppercase tracking-[0.16em]">
        qualreviews · ↘
      </div>
      </div>
    </footer>
  );
}
