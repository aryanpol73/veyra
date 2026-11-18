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
