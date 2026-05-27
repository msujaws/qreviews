export interface Group {
  slug: string;
  enabled: boolean;
  risk_threshold: number;
  complexity_threshold: number;
  has_skill: boolean;
}

export interface Summary {
  group_slug: string | null;
  since: number | null;
  revisions_seen: number;
  revisions_scored: number;
  revisions_posted: number;
  revisions_skipped: number;
  coverage_pct: number;
  median_risk: number | null;
  median_complexity: number | null;
  median_time_to_post_seconds: number | null;
  estimated_cost_usd: number;
  time_saved_hours: number;
  tokens: Record<string, number>;
}

export interface Histograms {
  risk: number[];
  complexity: number[];
}

export interface TimeseriesPoint {
  date: string;
  seen: number;
  posted: number;
  cost_usd: number;
}

export interface InlineFinding {
  file_path: string;
  line: number;
  is_new_file: boolean;
  body: string;
  confidence: number;
}

export interface RevisionDetail {
  revision_phid: string;
  revision_id: number;
  diff_id: number | null;
  group_slug: string;
  title: string | null;
  author_phid: string | null;
  revision_created_at: number | null;
  seen_at: number | null;
  scored_at: number | null;
  risk: number | null;
  complexity: number | null;
  risk_factors: string[];
  complexity_factors: string[];
  scoring_model: string | null;
  review_model: string | null;
  review_body: string | null;
  test_files_changed: number | null;
  non_test_files_changed: number | null;
  in_diff_test_signal: string | null;
  coverage_signal: string | null;
  inline_count: number;
  findings: InlineFinding[];
  posted: boolean;
  posted_at: number | null;
  skipped_reason: string | null;
  final_status: string | null;
  closed_at: number | null;
  human_first_response_at: number | null;
  tokens: {
    scoring: { input: number; output: number; cache_read: number; cache_write: number };
    review: { input: number; output: number; cache_read: number; cache_write: number; tool_calls: number };
  };
  estimated_cost_usd: number;
}

export interface AppConfig {
  default_thresholds: { risk: number; complexity: number };
  groups: string[];
}
