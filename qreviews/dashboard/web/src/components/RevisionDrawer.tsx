import { Drawer, Loader } from "@mantine/core";
import { useRevisionDetail } from "../hooks/useDashboardData";
import { Eyebrow } from "./Eyebrow";
import { MarkdownView } from "./MarkdownView";
import { ScoreBadge } from "./ScoreBadge";

interface Props {
  revisionId: number | null;
  riskThreshold: number;
  complexityThreshold: number;
  onClose: () => void;
}

function fmtTs(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "$0.00";
  return `$${Number(n).toFixed(4)}`;
}

export function RevisionDrawer({
  revisionId,
  riskThreshold,
  complexityThreshold,
  onClose,
}: Props) {
  const { data, isLoading } = useRevisionDetail(revisionId);

  return (
    <Drawer
      opened={revisionId !== null}
      onClose={onClose}
      position="right"
      size="lg"
      withCloseButton={false}
      padding={0}
      overlayProps={{ backgroundOpacity: 0.7, color: "var(--pt-bg)" }}
      styles={{
        content: { background: "var(--pt-bg)" },
        body: { padding: 0, background: "var(--pt-bg)" },
      }}
    >
      <div className="px-8 py-7 flex flex-col gap-7">
        {isLoading || !data ? (
          <div className="flex items-center justify-center h-[60vh]">
            <Loader color="flame" size="sm" />
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between gap-6">
              <div>
                <Eyebrow>differential revision</Eyebrow>
                <div className="mt-2 pt-numeral text-[40px] leading-none">
                  D{data.revision_id}
                </div>
                <div className="mt-2 pt-mono text-[12px]">
                  <a
                    href={`https://phabricator.services.mozilla.com/D${data.revision_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[var(--pt-flame)] border-b border-dotted border-[var(--pt-flame)]/60 hover:border-[var(--pt-flame)]"
                  >
                    open in phabricator →
                  </a>
                </div>
              </div>
              <button
                onClick={onClose}
                className="pt-mono text-[12px] text-[var(--pt-muted)] hover:text-[var(--pt-ink)] uppercase tracking-[0.12em] cursor-pointer"
                aria-label="close drawer"
              >
                close ✕
              </button>
            </div>

            <div className="pt-surface px-5 py-4">
              <Eyebrow rule>title</Eyebrow>
              <div className="mt-3 text-[15px] leading-[1.5] text-[var(--pt-ink)]">
                {data.title || "—"}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 pt-mono text-[11px]">
                <Field label="group" value={data.group_slug} />
                <Field label="author" value={data.author_phid || "—"} mono />
                <Field label="created" value={fmtTs(data.revision_created_at)} />
                <Field label="seen" value={fmtTs(data.seen_at)} />
                <Field label="posted" value={fmtTs(data.posted_at)} />
                <Field label="cost" value={fmtMoney(data.estimated_cost_usd)} />
                <Field label="scoring" value={data.scoring_model || "—"} mono />
                <Field label="review" value={data.review_model || "—"} mono />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <ScoreCard
                axis="risk"
                value={data.risk}
                threshold={riskThreshold}
                factors={data.risk_factors}
              />
              <ScoreCard
                axis="complexity"
                value={data.complexity}
                threshold={complexityThreshold}
                factors={data.complexity_factors}
              />
            </div>

            <TestSignalCard
              inDiffSignal={data.in_diff_test_signal}
              coverageSignal={data.coverage_signal}
              testFiles={data.test_files_changed}
              nonTestFiles={data.non_test_files_changed}
            />

            {data.findings && data.findings.length > 0 && (
              <div className="pt-surface px-5 py-5">
                <Eyebrow rule>inline findings ({data.findings.length})</Eyebrow>
                <ul className="mt-4 space-y-3">
                  {data.findings.map((f, i) => (
                    <li key={i} className="border-l-2 border-[var(--pt-flame)]/60 pl-3">
                      <div className="pt-mono text-[11px] text-[var(--pt-muted)]">
                        <a
                          href={`https://phabricator.services.mozilla.com/D${data.revision_id}#inline-${f.line}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[var(--pt-flame)] border-b border-dotted border-[var(--pt-flame)]/60 hover:border-[var(--pt-flame)]"
                        >
                          {f.file_path}:{f.line}
                          {f.is_new_file ? "" : " (old)"}
                        </a>
                        <span className="ml-2 text-[var(--pt-muted)]">
                          confidence {Math.round((f.confidence || 0) * 100)}%
                        </span>
                      </div>
                      <div className="mt-1 text-[13px] leading-[1.5] text-[var(--pt-ink)]">
                        {f.body}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="pt-surface px-5 py-5 border-l-2 border-l-[var(--pt-flame)] rounded-sm">
              <Eyebrow rule>posted summary comment</Eyebrow>
              <div className="mt-4">
                <MarkdownView source={data.review_body} />
              </div>
            </div>
          </>
        )}
      </div>
    </Drawer>
  );
}

function TestSignalCard({
  inDiffSignal,
  coverageSignal,
  testFiles,
  nonTestFiles,
}: {
  inDiffSignal: string | null;
  coverageSignal: string | null;
  testFiles: number | null;
  nonTestFiles: number | null;
}) {
  if (!inDiffSignal && !coverageSignal) return null;
  return (
    <div className="pt-surface px-5 py-4">
      <Eyebrow rule>test signals</Eyebrow>
      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 pt-mono text-[11px]">
        <Field label="in-diff" value={inDiffSignal || "—"} />
        <Field label="existing coverage" value={coverageSignal || "—"} />
        <Field
          label="test files"
          value={testFiles == null ? "—" : String(testFiles)}
        />
        <Field
          label="non-test files"
          value={nonTestFiles == null ? "—" : String(nonTestFiles)}
        />
      </div>
    </div>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[var(--pt-muted)] uppercase tracking-[0.12em] text-[10px]">{label}</span>
      <span className={`text-[var(--pt-ink)] ${mono ? "" : ""} truncate`}>{value}</span>
    </div>
  );
}

interface ScoreCardProps {
  axis: string;
  value: number | null;
  threshold: number;
  factors: string[];
}

function ScoreCard({ axis, value, threshold, factors }: ScoreCardProps) {
  return (
    <div className="pt-surface px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>{axis}</Eyebrow>
        <ScoreBadge value={value} threshold={threshold} />
      </div>
      <ul className="mt-3 space-y-1.5 pt-mono text-[12px] text-[var(--pt-ink)]/85 list-disc list-inside">
        {factors.length === 0 ? (
          <li className="text-[var(--pt-muted)] italic">(none recorded)</li>
        ) : (
          factors.map((f, i) => <li key={i}>{f}</li>)
        )}
      </ul>
    </div>
  );
}
