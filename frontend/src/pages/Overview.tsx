import Notifications from "../components/Notifications";
import { CSSProperties, useState } from "react";
import { Link } from "react-router-dom";
import { AlertItem, api, Health, Overview as OverviewData } from "../api/client";
import {
  Badge, Card, ConfidenceRing, Empty, ErrorBox, ExtLink, PageHeader, PriorityTag, Skeleton, Stat, StatusTag,
  btnCls, btnSecondaryCls, btnSmCls, useLoad,
} from "../components/ui";
import { IconArrowRight, IconRefresh } from "../components/icons";

const fmt = (d: string) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" });

function AlertRow({ a, onRated, i }: { a: AlertItem; onRated: () => void; i: number }) {
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
    <li className="anim-rise border-t border-line px-4 py-3.5 first:border-t-0" style={{ "--i": i } as CSSProperties}>
      <div className="flex flex-wrap items-center gap-1.5">
        <PriorityTag priority={a.priority} />
        <Badge>{a.competitor}</Badge>
        <span className="tnum ml-auto font-mono text-[11px] text-muted">{new Date(a.created_at).toLocaleString()}</span>
      </div>
      <div className="mt-1.5 text-sm font-medium leading-snug text-ink">
        {a.hypothesis_id ? <Link className="underline-offset-2 hover:underline" to={`/hypotheses?id=${a.hypothesis_id}`}>{a.title}</Link> : a.title}
      </div>
      <div className="mt-1 whitespace-pre-line text-xs leading-relaxed text-muted [overflow-wrap:anywhere]">{[title, ...rest].slice(0, 3).join("\n")}</div>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {rated ? (
          <Badge tone={rated === "useful" ? "ok" : "muted"}>rated {rated}</Badge>
        ) : (
          <>
            <span className="font-mono text-[11px] text-muted">Was this useful?</span>
            <button disabled={busy} onClick={() => rate(true)} className={btnSmCls}>Useful</button>
            <button disabled={busy} onClick={() => rate(false)} className={btnSmCls}>Noise</button>
          </>
        )}
      </div>
    </li>
  );
}

function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-4 p-4">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="space-y-2"><Skeleton className="h-3 w-1/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-1.5 w-full" /></div>
      ))}
    </div>
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
  const allLink = (to: string, label: string) => (
    <Link to={to} className="inline-flex items-center gap-1 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-muted transition-colors hover:text-accent">
      {label}<IconArrowRight size={12} />
    </Link>
  );

  return (
    <div className="space-y-5">
      <PageHeader
        index="01"
        title="Overview"
        description="What changed across tracked competitors, which hypotheses are moving, and which alerts fired."
        actions={<button className={btnSecondaryCls} onClick={() => { reload(); reloadAlerts(); }}><IconRefresh />Refresh</button>}
      />
      {(err || alertErr) && <ErrorBox error={`Couldn't load the overview: ${err ?? alertErr}`} />}

      {k && k.competitors === 0 && (
        <section aria-labelledby="welcome" className="rounded-[12px] border border-line bg-surface p-6">
          <h2 id="welcome" className="font-display text-lg font-semibold text-ink">Welcome to Veyra</h2>
          <p className="mt-1 max-w-[65ch] text-sm text-ink-2">
            Veyra is empty until you tell it who to watch. It works for companies in any field.
          </p>
          <ol className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
            {[
              ["Add a competitor", "Type its domain on Competitors and press Discover; Veyra finds its pricing page, feeds and job board."],
              ["Run a cycle", "On the Intelligence Feed, press Run cycle now to collect signals from every source."],
              ["Read the hypotheses", "With an LLM key in .env, the agents form, investigate and challenge hypotheses."],
            ].map(([title, body], i) => (
              <li key={title} className="rounded-[8px] border border-line p-3">
                <div className="font-mono text-[11px] text-accent">{String(i + 1).padStart(2, "0")}</div>
                <div className="mt-1 font-medium text-ink">{title}</div>
                <p className="mt-1 text-xs text-ink-2">{body}</p>
              </li>
            ))}
          </ol>
          <Link to="/competitors" className={`${btnCls} mt-5 inline-flex`}>Add your first competitor<IconArrowRight size={14} /></Link>
        </section>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {k ? (
          <>
            <Stat index={0} label="Competitors" value={k.competitors} sub="tracked" />
            <Stat index={1} label="Signals · 7 days" value={k.signals_7d} sub={`of ${k.signals_total} total`} />
            <Stat index={2} label="Open hypotheses" value={k.open_hypotheses} sub={`${k.likely_or_confirmed} likely+`} />
            <Stat index={3} label="Alerts" value={k.alerts} sub={`${k.alerts_rated_useful} useful · ${k.alerts_rated_noise} noise`} />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="rounded-[12px] border border-line bg-surface p-4"><Skeleton className="h-3 w-20" /><Skeleton className="mt-3 h-7 w-14" /><Skeleton className="mt-2.5 h-3 w-24" /></div>
          ))
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Card title="Top hypotheses" right={allLink("/hypotheses", "All")} flush>
          {!data && !err && <ListSkeleton />}
          {data && data.top_hypotheses.length === 0 && <div className="p-4"><Empty>No hypotheses yet. Run a cycle with an LLM key set.</Empty></div>}
          <ul>
            {data?.top_hypotheses.map((h, i) => (
              <li key={h.id} className="anim-rise border-t border-line first:border-t-0" style={{ "--i": i } as CSSProperties}>
                <Link to={`/hypotheses?id=${h.id}`} className="group flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-[color-mix(in_srgb,var(--accent)_5%,transparent)]">
                  <ConfidenceRing value={h.confidence} status={h.status} size={54} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusTag status={h.status} />
                      <span className="font-mono text-[11px] text-muted">{h.competitor}</span>
                    </div>
                    <div className="mt-1.5 text-sm leading-snug text-ink group-hover:underline group-hover:decoration-line-strong group-hover:underline-offset-2">{h.statement}</div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <p className="border-t border-line px-4 py-2.5 font-mono text-[11px] text-muted">Scores are an uncalibrated heuristic.</p>
        </Card>

        <Card title="Latest alerts" flush>
          {!alerts && !alertErr && <ListSkeleton />}
          {alerts && alerts.length === 0 && <div className="p-4"><Empty>No alerts yet. Alerts fire when a hypothesis is raised to likely after the skeptic has challenged it, or on a critical signal.</Empty></div>}
          <ul>{alerts?.map((a, i) => <AlertRow key={a.id} a={a} onRated={reload} i={i} />)}</ul>
        </Card>
      </div>

      <Card title="High-priority signals" right={allLink("/feed", "Feed")} flush>
        {!data && !err && <ListSkeleton rows={2} />}
        {data && data.hot_signals.length === 0 && <div className="p-4"><Empty>No high or critical signals yet.</Empty></div>}
        <ul>
          {data?.hot_signals.map((s, i) => (
            <li key={s.id} className="anim-rise grid gap-x-4 gap-y-1.5 border-t border-line px-4 py-3 first:border-t-0 sm:grid-cols-[9.5rem_minmax(0,1fr)_auto] sm:items-baseline" style={{ "--i": i } as CSSProperties}>
              <div className="flex items-center gap-2">
                <PriorityTag priority={s.priority} />
                <span className="tnum font-mono text-[11px] text-muted">{fmt(s.observed_at)}</span>
              </div>
              <div className="min-w-0 text-sm leading-snug text-ink">
                <span className="mr-2 font-mono text-[11px] text-muted">{s.competitor}</span>{s.summary}
              </div>
              <ExtLink href={s.evidence_url}>evidence</ExtLink>
            </li>
          ))}
        </ul>
      </Card>

      <Notifications />

      {health && (
        <Card title="System" right={<button className={btnCls} onClick={testLlm} disabled={pinging}>{pinging ? "Testing…" : "Test LLM"}</button>}>
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div><dt className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">API / DB</dt>
              <dd className="mt-1.5 flex flex-wrap gap-1.5"><Badge tone="ok">{health.status}</Badge> <Badge tone="ok">db {health.db}</Badge></dd></div>
            <div><dt className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">LLM</dt>
              <dd className="mt-1.5 flex flex-wrap items-center gap-1.5 text-ink">{health.llm.provider} {health.llm.configured ? <Badge tone="ok">configured</Badge> : <Badge tone="warn">no API key in .env</Badge>}</dd></div>
            <div className="min-w-0"><dt className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">Models</dt>
              <dd className="mt-1.5 font-mono text-xs text-ink-2 [overflow-wrap:anywhere]">{health.llm.strong} / {health.llm.fast}</dd></div>
            <div><dt className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">LLM ping</dt>
              <dd className="mt-1.5">{ping ? (ping.ok ? <Badge tone="ok">ok</Badge> : <Badge tone="bad">{ping.error}</Badge>) : <span className="font-mono text-xs text-muted">not tested</span>}</dd></div>
          </dl>
        </Card>
      )}
    </div>
  );
}
