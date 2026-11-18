// Thin typed API client. Vite proxies /api -> FastAPI on :8000.
const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${body.slice(0, 300)}`);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

export const api = {
  get: <T>(p: string) => req<T>(p),
  post: <T>(p: string, body?: unknown) => req<T>(p, { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T>(p: string, body: unknown) => req<T>(p, { method: "PUT", body: JSON.stringify(body) }),
  del: (p: string) => req<void>(p, { method: "DELETE" }),
};

// ---- types (mirror backend schemas) ----
export interface Health {
  status: string;
  db: string;
  llm: { provider: string; base_url: string; strong: string; fast: string; configured: boolean; ping?: { ok: boolean; reply?: string; error?: string } };
  counts: { competitors: number; signals: number; hypotheses: number; agent_runs: number };
}

export interface Source {
  id: number;
  source_type: "page" | "jobs" | "news" | "early_signal";
  url: string;
  active: boolean;
  last_checked_at: string | null;
  last_status: string | null;
}

export interface CompetitorIn {
  name: string;
  domain: string;
  pricing_url?: string | null;
  product_urls: string[];
  careers_provider?: "greenhouse" | "lever" | null;
  careers_token?: string | null;
  news_query?: string | null;
  feed_urls?: string[];
  notes?: string | null;
}

export interface Competitor extends CompetitorIn {
  id: number;
  created_at: string;
  sources: Source[];
}

export interface Signal {
  id: number;
  competitor_id: number;
  competitor: string | null;
  source_id: number | null;
  type: string;
  category: "pricing" | "product" | "hiring" | "market" | "early_signal";
  summary: string;
  old_value: string | null;
  new_value: string | null;
  evidence_url: string;
  observed_at: string;
  detected_at: string;
  origin_group: string;
  event_confidence: number;
  priority: "critical" | "high" | "medium" | "low";
  raw: Record<string, any>;
  synthetic: boolean;
  replay: boolean;
}

export interface CycleStatus {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  current: string | null;
  signals_created: number;
  errors: number;
  sources: { competitor: string; source_type: string; url: string; status: string; signals: number; error?: string }[];
}

export interface HypothesisSummary {
  id: number;
  competitor_id: number;
  competitor: string;
  statement: string;
  category: string;
  status: "emerging" | "plausible" | "likely" | "confirmed" | "refuted" | "stale";
  confidence: number;
  band: string;
  prior: number;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  evidence_for: number;
  evidence_against: number;
  replay: boolean;
  synthetic: boolean;
  score_label: string;
}

export interface HypothesisDetail extends HypothesisSummary {
  testable_predictions: { claim: string; horizon_days: number; signal_types: string[]; keywords: string[] }[];
  evidence_needed: string[];
  evidence: {
    id: number;
    stance: "supports" | "contradicts" | "neutral";
    relevance: number;
    reliability: number;
    independence_weight: number;
    contribution: number;
    rationale: string;
    added_by: string;
    signal: Signal;
  }[];
  belief_history: { ts: string; confidence: number; delta: number; reason: string; evidence_ids: number[] }[];
  challenges: { id: number; alternative: string; discriminating_test: string; test_result: string | null; verdict: string; created_at: string }[];
  investigations: {
    id: number;
    started_at: string;
    plan: string[];
    actions: { tool: string; args: Record<string, unknown>; result: string }[];
    findings: { signal_id?: number; url?: string; summary: string; stance?: string; relevance?: number; dropped?: boolean; why?: string }[];
    stop_reason: string | null;
    tokens: number;
  }[];
  predictions: { id: number; claim: string; made_at: string; horizon_days: number; resolve_by: string; confidence_at_creation: number; outcome: string; resolved_at: string | null }[];
}

export interface AlertItem {
  id: number;
  competitor: string;
  hypothesis_id: number | null;
  signal_id: number | null;
  priority: string;
  title: string;
  body: string;
  created_at: string;
  feedback: string | null;
}

export interface CalibrationBin { bin: string; range: [number, number]; n: number; hits: number; mean_confidence: number | null; observed_rate: number | null; wilson_95: [number, number] | null }
export interface EvalEventRow { id: string; competitor: string; label: string; category: string; public_date: string; source_url: string; detected_at: string | null; lead_days: number | null; matched_hypothesis_id: number | null; matched_statement: string | null; is_true_positive: boolean }
export interface EvalRun {
  id: number;
  created_at: string;
  mode: "masked" | "none" | "post_cutoff";
  config: Record<string, any>;
  metrics: {
    n_events: number; n_hypotheses: number; n_detected: number; true_positives: number;
    precision: number | null; recall: number | null; fp_rate: number | null; false_alarms_per_competitor_month: number | null;
    lead_days: number[]; lead_median: number | null; early_detections: number;
    brier_hypotheses: number | null; brier_predictions: number | null; n_predictions_resolved: number;
    calibration: CalibrationBin[]; events: EvalEventRow[]; config: Record<string, any>;
    hypotheses: { id: number; competitor: string; statement: string; final_confidence: number; detected_at: string | null; matched_event: string | null }[];
    synthetic_test?: { passed: boolean; expectation: string; [k: string]: any };
  };
}
export interface EvalStatus { running: boolean; mode: string | null; started_at: string | null; exit_code: number | null; log_tail: string }
