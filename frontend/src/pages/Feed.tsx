import { useEffect, useMemo, useRef, useState } from "react";
import { api, Competitor, CycleStatus, Signal } from "../api/client";
import { Badge, Card, Empty, ErrorBox, btnCls, inputCls, useLoad } from "../components/ui";

const PRIORITY_TONE = { critical: "bad", high: "warn", medium: "info", low: "muted" } as const;
const CATEGORIES = ["pricing", "product", "hiring", "market", "early_signal"];
const PRIORITIES = ["critical", "high", "medium", "low"];

const fmt = (d: string) => new Date(d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
const label = (t: string) => t.replace(/_/g, " ");

function SignalCard({ s, related }: { s: Signal; related: number }) {
  const [open, setOpen] = useState(false);
  const hasDetail = (s.raw.added?.length || s.raw.removed?.length || s.raw.postings?.length || s.raw.paths?.length || s.raw.caveat) > 0;
  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Badge tone={PRIORITY_TONE[s.priority]}>{s.priority}</Badge>
        <Badge>{s.competitor}</Badge>
        <span className="font-medium text-zinc-700 dark:text-zinc-300">{label(s.type)}</span>
        {s.category === "early_signal" && <Badge tone="warn">Early Signal</Badge>}
        {s.type === "removal" && <Badge tone="bad">Removal</Badge>}
        {s.synthetic && <Badge tone="synthetic">Synthetic</Badge>}
        {s.replay && <Badge tone="synthetic">Replay</Badge>}
        {s.raw.classified_by && <Badge tone="muted">{s.raw.classified_by === "llm" ? "LLM-classified" : "rule-classified"}</Badge>}
        {related > 1 && <Badge tone="muted">{related} items, 1 origin</Badge>}
        <span className="ml-auto text-zinc-500" title={`detected ${new Date(s.detected_at).toLocaleString()}`}>
          observed {fmt(s.observed_at)} · detected {fmt(s.detected_at)}
        </span>
      </div>
      <p className="mt-1.5 text-sm">{s.summary}</p>
      {(s.old_value || s.new_value) && s.type !== "news_mention" && (
        <p className="mt-1 text-xs text-zinc-500 break-words">
          {s.old_value && <><span className="line-through">{s.old_value.slice(0, 160)}</span> → </>}
          <span className="text-zinc-700 dark:text-zinc-300">{s.new_value?.slice(0, 200) ?? "—"}</span>
        </p>
      )}
      <div className="mt-1.5 flex flex-wrap gap-3 text-xs">
        <a className="text-sky-700 hover:underline dark:text-sky-400 break-all" href={s.evidence_url} target="_blank" rel="noreferrer">evidence ↗</a>
        {s.raw.previous_version_url && (
          <a className="text-sky-700 hover:underline dark:text-sky-400" href={s.raw.previous_version_url} target="_blank" rel="noreferrer">previous version (Wayback) ↗</a>
        )}
        {s.raw.publisher && <span className="text-zinc-500">{s.raw.publisher}</span>}
        {hasDetail && <button className="text-zinc-500 hover:underline" onClick={() => setOpen((o) => !o)}>{open ? "hide detail" : "detail"}</button>}
      </div>
      {open && (
        <div className="mt-2 space-y-1 rounded bg-zinc-50 p-2 font-mono text-xs dark:bg-zinc-950">
          {s.raw.caveat && <div className="text-amber-700 dark:text-amber-400">caveat: {s.raw.caveat}</div>}
          {s.raw.removed?.slice(0, 12).map((l: string, i: number) => <div key={"r" + i} className="text-red-700 dark:text-red-400">- {l}</div>)}
          {s.raw.added?.slice(0, 12).map((l: string, i: number) => <div key={"a" + i} className="text-emerald-700 dark:text-emerald-400">+ {l}</div>)}
          {s.raw.postings?.slice(0, 10).map((p: { title: string; url: string }, i: number) => (
            <div key={"p" + i}><a className="hover:underline" href={p.url} target="_blank" rel="noreferrer">{p.title}</a></div>
          ))}
          {s.raw.paths?.slice(0, 10).map((p: string) => <div key={p}>{p}</div>)}
        </div>
      )}
    </article>
  );
}

function CyclePanel({ onDone }: { onDone: () => void }) {
  const [st, setSt] = useState<CycleStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number>();
  const wasRunning = useRef(false);

  async function poll() {
    try {
      const s = await api.get<CycleStatus>("/cycle/status");
      setSt(s);
      if (wasRunning.current && !s.running) onDone();
      wasRunning.current = s.running;
      timer.current = window.setTimeout(poll, s.running ? 1500 : 10000);
    } catch (e) {
      setErr(String(e));
    }
  }
  useEffect(() => {
    poll();
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run() {
    setErr(null);
    try {
      await api.post("/cycle/run");
      wasRunning.current = true;
      window.clearTimeout(timer.current);
      poll();
    } catch (e) {
      setErr(String((e as Error).message));
    }
  }

  const failed = st?.sources.filter((s) => s.status !== "ok") ?? [];
  return (
    <Card title="Collection cycle" right={<button className={btnCls} disabled={st?.running} onClick={run}>{st?.running ? "Running…" : "Run cycle now"}</button>}>
      {err && <ErrorBox error={err} />}
      {st && (
        <div className="text-sm text-zinc-600 dark:text-zinc-400">
          {st.running ? (
            <>Checking <span className="font-mono text-xs">{st.current}</span> · {st.sources.length} sources done · {st.signals_created} new signals</>
          ) : st.finished_at ? (
            <>Last cycle finished {new Date(st.finished_at).toLocaleString()}: {st.sources.length} sources, {st.signals_created} new signals, {st.errors} problem(s).</>
          ) : (
            <>No cycle run since the server started.</>
          )}
          {failed.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs">
              {failed.map((f, i) => (
                <li key={i}><Badge tone={f.status === "robots-blocked" ? "warn" : "bad"}>{f.status}</Badge> {f.competitor} {f.source_type}: <span className="break-all">{f.error}</span></li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

export default function Feed() {
  const [competitors] = useLoad(() => api.get<Competitor[]>("/competitors"));
  const [comp, setComp] = useState("");
  const [cat, setCat] = useState("");
  const [prio, setPrio] = useState("");
  const qs = new URLSearchParams(Object.entries({ competitor: comp, category: cat, priority: prio }).filter(([, v]) => v)).toString();
  const [signals, err, reload] = useLoad(() => api.get<Signal[]>(`/signals?limit=300${qs ? "&" + qs : ""}`), [qs]);

  const groupSize = useMemo(() => {
    const m = new Map<string, number>();
    signals?.forEach((s) => m.set(s.origin_group, (m.get(s.origin_group) ?? 0) + 1));
    return m;
  }, [signals]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Intelligence Feed</h1>
      <CyclePanel onDone={reload} />
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <select className={inputCls} value={comp} onChange={(e) => setComp(e.target.value)} aria-label="Competitor">
          <option value="">All competitors</option>
          {competitors?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className={inputCls} value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
        </select>
        <select className={inputCls} value={prio} onChange={(e) => setPrio(e.target.value)} aria-label="Priority">
          <option value="">All priorities</option>
          {PRIORITIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      {err && <ErrorBox error={err} />}
      {signals && signals.length === 0 && <Empty>No signals match. Run a cycle, or loosen the filters.</Empty>}
      {signals && signals.length > 0 && <div className="text-xs text-zinc-500">{signals.length} signals · newest observed first</div>}
      <div className="space-y-2">
        {signals?.map((s) => <SignalCard key={s.id} s={s} related={groupSize.get(s.origin_group) ?? 1} />)}
      </div>
    </div>
  );
}
