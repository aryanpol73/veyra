import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { api, ChatReply, Timeline } from "../api/client";
import { Badge, ErrorBox, btnCls, inputCls } from "../components/ui";
import Markdown from "../components/Markdown";

interface Turn { role: "user" | "assistant"; content: string; reply?: ChatReply }

const SUGGESTIONS = [
  "How has Vercel's pricing strategy evolved?",
  "What is Figma doing with AI, and how sure are we?",
  "Which hypotheses did the skeptic weaken, and why?",
  "Compare recent pricing changes across competitors",
];

function MiniTimeline({ t }: { t: Timeline }) {
  const data = t.points.map((p, i) => ({ i, c: p.confidence, reason: p.reason, ts: p.ts }));
  return (
    <div className="rounded border border-zinc-200 p-2 dark:border-zinc-800">
      <div className="flex items-center gap-2 text-xs">
        <Badge>{t.competitor}</Badge>
        <Link className="min-w-0 flex-1 truncate hover:underline" to={`/hypotheses?id=${t.hypothesis_id}`}>H{t.hypothesis_id}: {t.statement}</Link>
        <span className="tabular-nums text-zinc-500">{t.band} {t.confidence.toFixed(2)}</span>
      </div>
      {data.length > 1 ? (
        <div className="mt-1 h-20">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <YAxis domain={[0, 1]} hide />
              <Tooltip content={({ active, payload }) => {
                const p = active && payload?.[0]?.payload;
                return p ? (
                  <div className="max-w-xs rounded border border-zinc-200 bg-white p-1.5 text-xs shadow dark:border-zinc-700 dark:bg-zinc-900">
                    <b className="tabular-nums">{p.c.toFixed(2)}</b> · {new Date(p.ts).toLocaleDateString()}<div className="text-zinc-500">{p.reason}</div>
                  </div>) : null;
              }} />
              <Line type="linear" dataKey="c" stroke="var(--series-1)" strokeWidth={2} isAnimationActive={false}
                dot={{ r: 3, fill: "var(--series-1)", stroke: "var(--chart-surface)", strokeWidth: 1.5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : <p className="mt-1 text-xs text-zinc-500">One belief update so far.</p>}
      <p className="text-[11px] text-zinc-500">Belief timeline from the database (uncalibrated heuristic score).</p>
    </div>
  );
}

function Reply({ r }: { r: ChatReply }) {
  const [showTools, setShowTools] = useState(false);
  return (
    <div className="space-y-2">
      <Markdown text={r.answer} />
      {r.timelines.length > 0 && <div className="grid gap-2 md:grid-cols-2">{r.timelines.map((t) => <MiniTimeline key={t.hypothesis_id} t={t} />)}</div>}
      {r.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {r.citations.map((c) => c.kind === "hypothesis" ? (
            <Link key={`h${c.id}`} to={c.url} className="rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800" title={c.label}>H{c.id} · {c.status}</Link>
          ) : (
            <a key={`s${c.id}`} href={c.url} target="_blank" rel="noreferrer" className="max-w-xs truncate rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800" title={c.label}>
              S{c.id} · {c.competitor} · {c.label} ↗
            </a>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
        {r.citations.length === 0 && !r.error && <Badge tone="warn">no sources cited</Badge>}
        {!!r.dropped_citations && <span>{r.dropped_citations} citation(s) dropped (not returned by a tool)</span>}
        {r.tool_calls.length > 0 && <button className="hover:underline" onClick={() => setShowTools((s) => !s)}>{showTools ? "hide" : "show"} {r.tool_calls.length} tool call(s)</button>}
      </div>
      {showTools && (
        <ul className="space-y-1 font-mono text-xs">
          {r.tool_calls.map((c, i) => <li key={i} className="rounded bg-zinc-50 p-1.5 dark:bg-zinc-950">{c.tool}({JSON.stringify(c.args)})<div className="whitespace-pre-line text-zinc-500">{c.result}</div></li>)}
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
    <div className="flex min-h-[calc(100vh-6rem)] flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Ask Veyra</h1>
        <p className="text-xs text-zinc-500">Answers come only from Veyra's database through read-only tools, with sources. Each question uses a few LLM calls.</p>
      </div>
      <div className="flex-1 space-y-4">
        {turns.length === 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => ask(s)} className="rounded-lg border border-zinc-200 bg-white p-3 text-left text-sm hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900">{s}</button>
            ))}
          </div>
        )}
        {turns.map((t, i) => t.role === "user" ? (
          <div key={i} className="ml-auto w-fit max-w-[85%] rounded-lg bg-zinc-900 px-3 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900">{t.content}</div>
        ) : (
          <div key={i} className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">{t.reply && <Reply r={t.reply} />}</div>
        ))}
        {busy && <div className="text-sm text-zinc-500">Looking through the database…</div>}
        {err && <ErrorBox error={err} />}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="sticky bottom-0 flex gap-2 bg-zinc-50 py-2 dark:bg-zinc-950">
        <input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about a competitor, a hypothesis, or a change over time" aria-label="Question" />
        <button className={btnCls} disabled={busy || !q.trim()} type="submit">Ask</button>
      </form>
    </div>
  );
}
