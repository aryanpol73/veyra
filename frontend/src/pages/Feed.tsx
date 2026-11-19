import { CSSProperties, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api, Competitor, CycleStatus, Signal } from "../api/client";
import { Badge, Card, Empty, ErrorBox, ExtLink, PageHeader, PriorityTag, ProvenanceTag, Skeleton, btnCls, inputCls, useLoad } from "../components/ui";
import { IconChevron, IconPlay } from "../components/icons";

const CATEGORIES = ["pricing", "product", "hiring", "market", "early_signal"];
const PRIORITIES = ["critical", "high", "medium", "low"];

const fmt = (d: string) => new Date(d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
const label = (t: string) => t.replace(/_/g, " ");

function SignalCard({ s, related, i }: { s: Signal; related: number; i: number }) {
  const [open, setOpen] = useState(false);
  const hasDetail = (s.raw.added?.length || s.raw.removed?.length || s.raw.postings?.length || s.raw.paths?.length || s.raw.caveat) > 0;
  return (
    <article className="anim-rise grid min-w-0 gap-x-5 gap-y-2 rounded-[4px] border border-line bg-surface p-4 sm:grid-cols-[8rem_minmax(0,1fr)]" style={{ "--i": Math.min(i, 10) } as CSSProperties}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 sm:flex-col sm:items-start sm:gap-1.5 sm:border-r sm:border-line sm:pr-4">
        <PriorityTag priority={s.priority} />
        <span className="tnum font-mono text-[11px] leading-tight text-ink-2" title={`detected ${new Date(s.detected_at).toLocaleString()}`}>
          <span className="text-muted sm:block">observed</span> {fmt(s.observed_at)}
        </span>
        <span className="tnum font-mono text-[11px] leading-tight text-ink-2"><span className="text-muted sm:block">detected</span> {fmt(s.detected_at)}</span>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge>{s.competitor}</Badge>
          <span className="font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-ink-2">{label(s.type)}</span>
          {s.category === "early_signal" && <ProvenanceTag kind="early" />}
          {s.type === "removal" && <Badge tone="bad">Removal</Badge>}
          {s.synthetic && <ProvenanceTag kind="synthetic" />}
          {s.replay && <ProvenanceTag kind="replay" />}
          {s.raw.classified_by && <Badge tone="muted">{s.raw.classified_by === "llm" ? "LLM-classified" : "rule-classified"}</Badge>}
          {related > 1 && <Badge tone="muted">{related} items, 1 origin</Badge>}
        </div>
        <p className="mt-2 text-sm leading-snug text-ink">{s.summary}</p>
        {(s.old_value || s.new_value) && s.type !== "news_mention" && (
          <p className="mt-2 rounded-[3px] bg-sunken px-2.5 py-1.5 font-mono text-xs leading-relaxed text-muted [overflow-wrap:anywhere]">
            {s.old_value && <><span className="line-through">{s.old_value.slice(0, 160)}</span> <span aria-hidden="true">→</span><span className="sr-only">changed to</span> </>}
            <span className="text-ink">{s.new_value?.slice(0, 200) ?? "—"}</span>
          </p>
        )}
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <ExtLink href={s.evidence_url}>evidence</ExtLink>
          {s.raw.previous_version_url && <ExtLink href={s.raw.previous_version_url}>previous version (Wayback)</ExtLink>}
          {s.raw.publisher && <span className="font-mono text-[11px] text-muted">{s.raw.publisher}</span>}
          {hasDetail && (
            <button className="inline-flex h-6 cursor-pointer items-center gap-1 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-muted hover:text-ink" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
              <span className={`transition-transform ${open ? "rotate-90" : ""}`}><IconChevron size={12} /></span>{open ? "hide detail" : "detail"}
            </button>
          )}
        </div>
        {open && (
          <div className="anim-route mt-2.5 space-y-0.5 rounded-[3px] border border-line bg-sunken p-2.5 font-mono text-xs leading-relaxed [overflow-wrap:anywhere]">
            {s.raw.caveat && <div style={{ color: "var(--warn)" }}>caveat: {s.raw.caveat}</div>}
            {s.raw.removed?.slice(0, 12).map((l: string, i: number) => <div key={"r" + i} style={{ color: "var(--bad)" }}>- {l}</div>)}
            {s.raw.added?.slice(0, 12).map((l: string, i: number) => <div key={"a" + i} style={{ color: "var(--ok)" }}>+ {l}</div>)}
            {s.raw.postings?.slice(0, 10).map((p: { title: string; url: string }, i: number) => (
              <div key={"p" + i}><a className="text-ink-2 hover:underline" href={p.url} target="_blank" rel="noreferrer">{p.title}</a></div>
            ))}
            {s.raw.paths?.slice(0, 10).map((p: string) => <div key={p} className="text-ink-2">{p}</div>)}
          </div>
        )}
      </div>
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
    <Card
      title={<span className="inline-flex items-center gap-2">
        <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${st?.running ? "anim-pulse bg-accent" : "bg-line-strong"}`} />Collection cycle
      </span>}
      right={<button className={btnCls} disabled={st?.running} onClick={run}><IconPlay />{st?.running ? "Running…" : "Run cycle now"}</button>}
      flush
    >
      <div className="relative h-0.5 overflow-hidden" aria-hidden="true">{st?.running && <div className="anim-scan absolute inset-y-0 w-1/4 bg-accent" />}</div>
      <div className="px-4 pb-4 pt-3.5">
        {err && <ErrorBox error={err} />}
        {!st && !err && <Skeleton className="h-4 w-2/3" />}
        {st && (
          <div className="text-sm text-ink-2" aria-live="polite">
            {st.running ? (
              <>Checking <span className="font-mono text-xs text-ink">{st.current}</span> · <span className="tnum">{st.sources.length}</span> sources done · <span className="tnum">{st.signals_created}</span> new signals</>
            ) : st.finished_at ? (
              <>Last cycle finished <span className="tnum font-mono text-xs text-ink">{new Date(st.finished_at).toLocaleString()}</span>: {st.sources.length} sources, {st.signals_created} new signals, {st.errors} problem(s).</>
            ) : (
              <>No cycle run since the server started.</>
            )}
            {failed.length > 0 && (
              <ul className="mt-3 space-y-1.5 border-t border-line pt-3 text-xs">
                {failed.map((f, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-1.5">
                    <Badge tone={f.status === "robots-blocked" ? "warn" : "bad"}>{f.status}</Badge>
                    <span className="font-medium text-ink">{f.competitor}</span> <span className="font-mono text-muted">{f.source_type}:</span>
                    <span className="min-w-0 break-all text-muted">{f.error}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function Field({ label: lbl, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">{lbl}</span>{children}
    </label>
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
    <div className="space-y-5">
      <PageHeader index="03" title="Intelligence Feed" description="Every detected change with its evidence link and provenance. Replay, Synthetic and Early Signal items are marked." />
      <CyclePanel onDone={reload} />
      <div className="grid grid-cols-1 gap-3 rounded-[4px] border border-line bg-surface p-3 sm:grid-cols-3">
        <Field label="Competitor">
          <select className={inputCls} value={comp} onChange={(e) => setComp(e.target.value)}>
            <option value="">All competitors</option>
            {competitors?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Category">
          <select className={inputCls} value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
          </select>
        </Field>
        <Field label="Priority">
          <select className={inputCls} value={prio} onChange={(e) => setPrio(e.target.value)}>
            <option value="">All priorities</option>
            {PRIORITIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
      </div>
      {err && <ErrorBox error={err} />}
      {signals && signals.length === 0 && <Empty>No signals match. Run a cycle, or loosen the filters.</Empty>}
      {signals && signals.length > 0 && (
        <div className="tnum font-mono text-[11px] uppercase tracking-[0.1em] text-muted">{signals.length} signals · newest observed first</div>
      )}
      {!signals && !err && (
        <div className="space-y-2">{[0, 1, 2].map((i) => (
          <div key={i} className="rounded-[4px] border border-line bg-surface p-4"><Skeleton className="h-3 w-1/3" /><Skeleton className="mt-3 h-4 w-full" /><Skeleton className="mt-2 h-3 w-1/2" /></div>
        ))}</div>
      )}
      <div className="space-y-2">
        {signals?.map((s, i) => <SignalCard key={s.id} s={s} i={i} related={groupSize.get(s.origin_group) ?? 1} />)}
      </div>
    </div>
  );
}
