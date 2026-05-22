interface Props {
  value: number | null | undefined;
  threshold: number;
}

export function ScoreBadge({ value, threshold }: Props) {
  if (value == null) {
    return <span className="pt-pill pt-pill--muted">—</span>;
  }
  let cls = "pt-pill--ok";
  if (value >= threshold) cls = value < threshold + 2 ? "pt-pill--warn" : "pt-pill--danger";
  return <span className={`pt-pill ${cls}`}>{value}/10</span>;
}
