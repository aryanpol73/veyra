import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertItem, api, Health, Overview as OverviewData } from "../api/client";
import { Badge, Card, Empty, ErrorBox, Stat, btnCls, useLoad } from "../components/ui";

const PRIORITY_TONE = { critical: "bad", high: "warn", medium: "info", low: "muted" } as const;
const STATUS_TONE = { emerging: "muted", plausible: "info", likely: "warn", confirmed: "ok", refuted: "bad", stale: "muted" } as const;
const fmt = (d: string) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function AlertRow({ a, onRated }: { a: AlertItem; onRated: () => void }) {
  const [busy, setBusy] = useState(false);
  const [rated, setRated] = useState(a.feedback);
  async function rate(useful: boolean) {
    setBusy(true);
    try {
      await api.post(`/alerts/${a.id}/feedback`, { useful });
      setRated(useful ? "useful" : "noise");
      onRated();
    } finally {
      setBusy(false);
    }
  }
  const [title, ...rest] = a.body.split("\n");
  return (
    <li className="border-t border-zinc-200 py-2 first:border-t-0 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Badge tone={PRIORITY_TONE[a.priority as keyof typeof PRIORITY_TONE] ?? "muted"}>{a.priority}</Badge>
        <Badge>{a.competitor}</Badge>
        <span className="text-zinc-500">{new Date(a.created_at).toLocaleString()}</span>
      </div>
      <div className="mt-1 text-sm font-medium">
        {a.hypothesis_id ? <Link className="hover:underline" to={`/hypotheses?id=${a.hypothesis_id}`}>{a.title}</Link> : a.title}
      </div>
      <div className="mt-0.5 whitespace-pre-line text-xs text-zinc-500">{[title, ...rest].slice(0, 3).join("\n")}</div>
      <div className="mt-1.5 flex items-center gap-2 text-xs">
        {rated ? (
          <Badge tone={rated === "useful" ? "ok" : "muted"}>rated {rated}</Badge>
        ) : (
          <>
            <span className="text-zinc-500">Was this useful?</span>
            <button disabled={busy} onClick={() => rate(true)} className="rounded border border-zinc-300 px-2 py-0.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">Useful</button>
            <button disabled={busy} onClick={() => rate(false)} className="rounded border border-zinc-300 px-2 py-0.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">Noise</button>
          </>
        )}
      </div>
    </li>
  );
}

export default function Overview() {
  const [data, err, reload] = useLoad(() => api.get<OverviewData>("/overview"));
  const [alerts, alertErr, reloadAlerts] = useLoad(() => api.get<AlertItem[]>("/alerts?limit=8"));
  const [health] = useLoad(() => api.get<Health>("/health"));
  const [ping, setPing] = useState<Health["llm"]["ping"] | null>(null);
  const [pinging, setPinging] = useState(false);

  async function testLlm() {
    setPinging(true);
    try {
      setPing((await api.get<Health>("/health?llm_check=true")).llm.ping ?? null);
    } catch (e) {
      setPing({ ok: false, error: String(e) });
    } finally {
      setPinging(false);
    }
  }

  const k = data?.kpis;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Overview</h1>
        <button className={btnCls} onClick={() => { reload(); reloadAlerts(); }}>Refresh</button>
      </div>
      {(err || alertErr) && <ErrorBox error={`Backend unreachable: ${err ?? alertErr}. Is FastAPI running on :8000?`} />}

      {k && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Competitors" value={k.competitors} />
          <Stat label="Signals (7 days)" value={<>{k.signals_7d}<span className="ml-1 text-sm font-normal text-zinc-500">/ {k.signals_total}</span></>} />
          <Stat label="Open hypotheses" value={<>{k.open_hypotheses}<span className="ml-1 text-sm font-normal text-zinc-500">{k.likely_or_confirmed} likely+</span></>} />
          <Stat label="Alerts" value={<>{k.alerts}<span className="ml-1 text-sm font-normal text-zinc-500">{k.alerts_rated_useful} useful · {k.alerts_rated_noise} noise</span></>} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Top hypotheses" right={<Link to="/hypotheses" className="text-xs text-zinc-500 hover:underline">all →</Link>}>
          {data && data.top_hypotheses.length === 0 && <Empty>No hypotheses yet. Run a cycle with an LLM key set.</Empty>}
          <ul className="space-y-2">
            {data?.top_hypotheses.map((h) => (
              <li key={h.id}>
                <Link to={`/hypotheses?id=${h.id}`} className="block rounded p-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                  <div className="flex items-center gap-2 text-xs text-zinc-500">
                    <Badge tone={STATUS_TONE[h.status]}>{h.status}</Badge>
                    <span className="tabular-nums">{h.confidence.toFixed(2)}</span><span>· {h.competitor}</span>
                  </div>
                  <div className="mt-0.5 text-sm">{h.statement}</div>
                </Link>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-zinc-500">Scores are an uncalibrated heuristic.</p>
        </Card>

        <Card title="Latest alerts">
          {alerts && alerts.length === 0 && <Empty>No alerts yet. Alerts fire when a hypothesis is raised to likely after the skeptic has challenged it, or on a critical signal.</Empty>}
          <ul>{alerts?.map((a) => <AlertRow key={a.id} a={a} onRated={reload} />)}</ul>
        </Card>
      </div>

      <Card title="High-priority signals" right={<Link to="/feed" className="text-xs text-zinc-500 hover:underline">feed →</Link>}>
        {data && data.hot_signals.length === 0 && <Empty>No high or critical signals yet.</Empty>}
        <ul className="space-y-1.5 text-sm">
          {data?.hot_signals.map((s) => (
            <li key={s.id} className="flex min-w-0 flex-wrap items-baseline gap-2">
              <Badge tone={PRIORITY_TONE[s.priority]}>{s.priority}</Badge>
              <span className="text-xs text-zinc-500">{s.competitor} · {fmt(s.observed_at)}</span>
              <a href={s.evidence_url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 hover:underline">{s.summary}</a>
            </li>
          ))}
        </ul>
      </Card>

      {health && (
        <Card title="System" right={<button className={btnCls} onClick={testLlm} disabled={pinging}>{pinging ? "Testing…" : "Test LLM"}</button>}>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
            <dt className="text-zinc-500">API / DB</dt>
            <dd><Badge tone="ok">{health.status}</Badge> <Badge tone="ok">db {health.db}</Badge></dd>
            <dt className="text-zinc-500">LLM</dt>
            <dd>{health.llm.provider} {health.llm.configured ? <Badge tone="ok">configured</Badge> : <Badge tone="warn">no API key in .env</Badge>}</dd>
            <dt className="text-zinc-500">Models</dt>
            <dd className="font-mono text-xs">{health.llm.strong} / {health.llm.fast}</dd>
            {ping && (<><dt className="text-zinc-500">LLM ping</dt><dd>{ping.ok ? <Badge tone="ok">ok</Badge> : <Badge tone="bad">{ping.error}</Badge>}</dd></>)}
          </dl>
        </Card>
      )}
    </div>
  );
}
