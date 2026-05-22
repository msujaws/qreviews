import type { RevisionDetail } from "../types";

export function StatusPill({ row }: { row: RevisionDetail }) {
  if (row.posted) return <span className="pt-pill pt-pill--ok">POSTED</span>;
  if (row.skipped_reason === "above_threshold")
    return <span className="pt-pill pt-pill--warn">ABOVE THRESHOLD</span>;
  if (row.skipped_reason === "oversized_diff")
    return <span className="pt-pill pt-pill--muted">TOO LARGE</span>;
  if (row.skipped_reason)
    return <span className="pt-pill pt-pill--muted">{row.skipped_reason.toUpperCase()}</span>;
  if (row.scored_at) return <span className="pt-pill pt-pill--muted">SCORED</span>;
  return <span className="pt-pill pt-pill--muted">SEEN</span>;
}
