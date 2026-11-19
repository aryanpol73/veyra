import { CSSProperties, FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { api, ChatReply, Timeline } from "../api/client";
import { Badge, ConfidenceGauge, ErrorBox, PageHeader, Skeleton, btnCls, inputCls } from "../components/ui";
import { IconArrowRight, IconChevron, IconExternal, IconSend, IconTool, VeyraMark } from "../components/icons";
import Markdown from "../components/Markdown";

interface Turn { role: "user" | "assistant"; content: string; reply?: ChatReply }

const SUGGESTIONS = [
  "How has each competitor's pricing evolved?",
  "Which competitor is most likely changing strategy, and how sure are we?",
  "Which hypotheses did the skeptic weaken, and why?",
  "Compare recent pricing changes across competitors",
];

function MiniTimeline({ t }: { t: Timeline }) {
  const data = t.points.map((p, i) => ({ i, c: p.confidence, reason: p.reason, ts: p.ts }));
  return (
    <div className="min-w-0 rounded-[6px] border border-line bg-surface-2 p-3">
      <div className="flex items-center gap-2">
        <Badge>{t.competitor}</Badge>
        <Link className="min-w-0 flex-1 truncate text-xs font-medium text-ink hover:underline" to={`/hypotheses?id=${t.hypothesis_id}`} title={t.statement}>
          <span className="font-mono text-accent">H{t.hypothesis_id}</span> {t.statement}
        </Link>
        <span className="tnum shrink-0 font-mono text-xs font-semibold text-ink">{t.band} {t.confidence.toFixed(2)}</span>
      </div>
      {data.length > 1 ? (
        <div className="mt-2 h-20">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <YAxis domain={[0, 1]} hide />
              <ReferenceLine y={0.7} stroke="var(--chart-ink)" strokeOpacity={0.4} strokeDasharray="3 3" />
              <Tooltip cursor={{ stroke: "var(--chart-ink)", strokeDasharray: "2 2" }} content={({ active, payload }) => {
                const p = active && payload?.[0]?.payload;
                return p ? (
                  <div className="max-w-xs rounded-[6px] border border-line-strong bg-surface p-2 text-xs shadow-lg">
                    <b className="tnum font-mono text-ink">{p.c.toFixed(2)}</b> <span className="font-mono text-muted">· {new Date(p.ts).toLocaleDateString()}</span><div className="mt-0.5 text-ink-2">{p.reason}</div>
                  </div>) : null;
              }} />
              <Line type="linear" dataKey="c" stroke="var(--series-1)" strokeWidth={1.5} isAnimationActive={false}
                dot={{ r: 2.5, fill: "var(--series-1)", stroke: "var(--chart-surface)", strokeWidth: 1 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : <div className="mt-3"><ConfidenceGauge value={t.confidence} /><p className="mt-2 text-xs text-muted">One belief update so far.</p></div>}
      <p className="mt-1.5 font-mono text-[10.5px] text-muted">Belief timeline from the database (uncalibrated heuristic score). Dashed = likely threshold.</p>
    </div>
  );
}

function Reply({ r }: { r: ChatReply }) {
  const [showTools, setShowTools] = useState(false);
  return (
    <div className="space-y-3">
      <Markdown text={r.answer} />
      {r.timelines.length > 0 && <div className="grid gap-2 md:grid-cols-2">{r.timelines.map((t) => <MiniTimeline key={t.hypothesis_id} t={t} />)}</div>}
      {r.citations.length > 0 && (
        <div className="border-t border-line pt-3">
          <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.1em] text-muted">Sources ({r.citations.length})</div>
          <div className="flex flex-wrap gap-1.5">
            {r.citations.map((c) => c.kind === "hypothesis" ? (
              <Link key={`h${c.id}`} to={c.url} title={c.label}
                className="inline-flex h-7 items-center gap-1.5 rounded-[6px] border border-line-strong bg-surface px-2 font-mono text-xs text-ink-2 transition-colors hover:border-accent hover:text-ink">
                <span className="font-semibold text-accent">H{c.id}</span>{c.status}<IconArrowRight size={11} />
              </Link>
            ) : (
              <a key={`s${c.id}`} href={c.url} target="_blank" rel="noreferrer" title={c.label}
                className="inline-flex h-7 max-w-xs items-center gap-1.5 rounded-[6px] border border-line-strong bg-surface px-2 font-mono text-xs text-ink-2 transition-colors hover:border-accent hover:text-ink">
                <span className="font-semibold text-ink">S{c.id}</span><span className="min-w-0 truncate">{c.competitor} · {c.label}</span><IconExternal className="shrink-0" />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            ))}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
        {r.citations.length === 0 && !r.error && <Badge tone="warn">no sources cited</Badge>}
        {!!r.dropped_citations && <span>{r.dropped_citations} citation(s) dropped (not returned by a tool)</span>}
        {r.tool_calls.length > 0 && (
          <button className="inline-flex h-6 cursor-pointer items-center gap-1 uppercase tracking-[0.06em] hover:text-ink" aria-expanded={showTools} onClick={() => setShowTools((s) => !s)}>
            <span className={`transition-transform ${showTools ? "rotate-90" : ""}`}><IconChevron size={12} /></span>{showTools ? "hide" : "show"} {r.tool_calls.length} tool call(s)
          </button>
        )}
      </div>
      {showTools && (
        <ul className="anim-route space-y-1.5 border-l border-line pl-3 font-mono text-xs">
          {r.tool_calls.map((c, i) => (
            <li key={i} className="rounded-[6px] bg-sunken p-2 [overflow-wrap:anywhere]">
              <span className="inline-flex items-center gap-1 font-medium text-accent"><IconTool size={12} />{c.tool}</span><span className="text-ink-2">({JSON.stringify(c.args)})</span>
              <div className="mt-1 whitespace-pre-line text-muted">{c.result}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Ask() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // block body: newer Chromium returns a Promise from scrollIntoView, which React would treat as a cleanup fn
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setErr(null);
    setBusy(true);
    const history = turns.map((t) => ({ role: t.role, content: t.content }));
    setTurns((t) => [...t, { role: "user", content: question }]);
    setQ("");
    try {
      const r = await api.post<ChatReply>("/chat", { question, history });
      setTurns((t) => [...t, { role: "assistant", content: r.answer, reply: r }]);
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); ask(q); };

  return (
    <div className="flex min-h-[calc(100dvh-12.5rem)] flex-col md:min-h-[calc(100dvh-6rem)]">
      <PageHeader index="05" title="Ask Veyra"
        description="Answers come only from Veyra's database through read-only tools, with sources. Each question uses a few LLM calls." />
      <div className="mx-auto w-full max-w-3xl flex-1 space-y-5">
        {turns.length === 0 && (
          <div>
            <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Try asking</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s, i) => (
                <button key={s} onClick={() => ask(s)} style={{ "--i": i } as CSSProperties}
                  className="anim-rise group flex cursor-pointer items-start justify-between gap-3 rounded-[12px] border border-line bg-surface p-3.5 text-left text-sm text-ink transition-colors hover:border-line-strong hover:bg-surface-2">
                  <span>{s}</span><span className="mt-0.5 text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-accent"><IconArrowRight /></span>
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => t.role === "user" ? (
          <div key={i} className="anim-rise ml-auto w-fit max-w-[85%] rounded-[12px] bg-ink px-3.5 py-2.5 text-sm leading-relaxed text-bg [overflow-wrap:anywhere]">{t.content}</div>
        ) : (
          <div key={i} className="anim-rise flex gap-3">
            <span className="mt-0.5 hidden shrink-0 sm:block"><VeyraMark size={24} /></span>
            <div className="min-w-0 flex-1 rounded-[12px] border border-line bg-surface p-4">{t.reply && <Reply r={t.reply} />}</div>
          </div>
        ))}
        {busy && (
          <div className="flex gap-3" role="status">
            <span className="mt-0.5 hidden shrink-0 sm:block"><VeyraMark size={24} /></span>
            <div className="min-w-0 flex-1 rounded-[12px] border border-line bg-surface p-4">
              <div className="flex items-center gap-2 font-mono text-xs text-ink-2"><span className="anim-pulse inline-block h-2 w-2 rounded-full bg-accent" aria-hidden="true" />Looking through the database…</div>
              <Skeleton className="mt-3 h-3 w-full" /><Skeleton className="mt-2 h-3 w-4/5" />
            </div>
          </div>
        )}
        {err && <ErrorBox error={err} />}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="sticky bottom-0 z-10 -mx-4 -mb-16 mt-6 border-t border-line bg-bg/95 px-4 py-3 backdrop-blur md:-mx-8 md:px-8">
        <div className="mx-auto flex max-w-3xl gap-2">
          <input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about a competitor, a hypothesis, or a change over time" aria-label="Question" />
          <button className={btnCls} disabled={busy || !q.trim()} type="submit"><IconSend size={14} /><span>Ask</span></button>
        </div>
      </form>
    </div>
  );
}
