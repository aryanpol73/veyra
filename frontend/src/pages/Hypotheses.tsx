import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Competitor, HypothesisDetail, HypothesisSummary } from "../api/client";
import { Badge, Card, Empty, ErrorBox, inputCls, useLoad } from "../components/ui";

const STATUS_TONE = { emerging: "muted", plausible: "info", likely: "warn", confirmed: "ok", refuted: "bad", stale: "muted" } as const;
const VERDICT_TONE: Record<string, "ok" | "bad" | "muted" | "warn"> = {
  alternative_refuted: "ok", alternative_supported: "bad", inconclusive: "muted", pending: "warn",
};
const fmtDate = (d: string) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const pct = (x: number) => x.toFixed(2);

function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-zinc-200 dark:bg-zinc-800" role="img" aria-label={`confidence ${pct(value)}`}>
      <div className="h-1.5 rounded-full" style={{ width: `${Math.round(value * 100)}%`, background: "var(--series-1)" }} />
    </div>
  );
}

function ScoreChip({ h }: { h: HypothesisSummary }) {
  return (
    <div className="flex items-center gap-2">
      <Badge tone={STATUS_TONE[h.status]}>{h.status}</Badge>
      <span className="text-sm font-semibold tabular-nums">{h.band} {pct(h.confidence)}</span>
      <span className="text-xs text-zinc-500" title="Not a validated probability until the Evaluation page shows calibration">
        {h.score_label}
      </span>
    </div>
  );
}

function BeliefChart({ d }: { d: HypothesisDetail }) {
  const data = d.belief_history.map((b, i) => ({ i, t: new Date(b.ts).getTime(), confidence: b.confidence, reason: b.reason, delta: b.delta }));
  if (data.length < 2) return <p className="text-sm text-zinc-500">Only one belief update so far; the timeline fills in as cycles run.</p>;
  const sameDay = new Date(data[0].t).toDateString() === new Date(data[data.length - 1].t).toDateString();
  const tick = (i: number) => sameDay ? `update ${i + 1}` : new Date(data[i]?.t ?? 0).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return (
    <div className="h-56 w-full" style={{ color: "var(--chart-ink)" }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 44, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="0" vertical={false} />
          <XAxis dataKey="i" tick={{ fontSize: 11, fill: "var(--chart-ink)" }} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }}
            tickFormatter={tick} />
          <YAxis domain={[0, 1]} ticks={[0, 0.4, 0.7, 0.9, 1]} width={36} tick={{ fontSize: 11, fill: "var(--chart-ink)" }} tickLine={false} axisLine={false} />
          {[{ y: 0.4, l: "plausible" }, { y: 0.7, l: "likely" }, { y: 0.9, l: "confirmed" }].map((r) => (
            <ReferenceLine key={r.y} y={r.y} stroke="var(--chart-grid)" strokeDasharray="4 4"
              label={{ value: r.l, position: "right", fontSize: 10, fill: "var(--chart-ink)" }} />
          ))}
          <Tooltip
            cursor={{ stroke: "var(--chart-ink)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0].payload as (typeof data)[number];
              return (
                <div className="max-w-xs rounded border border-zinc-200 bg-white p-2 text-xs shadow dark:border-zinc-700 dark:bg-zinc-900">
                  <div className="font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">{pct(p.confidence)} ({p.delta >= 0 ? "+" : ""}{pct(p.delta)})</div>
                  <div className="text-zinc-500">{new Date(p.t).toLocaleString()}</div>
                  <div className="mt-1 text-zinc-700 dark:text-zinc-300">{p.reason}</div>
                </div>
              );
            }}
          />
          <Line type="linear" dataKey="confidence" stroke="var(--series-1)" strokeWidth={2} isAnimationActive={false}
            dot={{ r: 4, fill: "var(--series-1)", stroke: "var(--chart-surface)", strokeWidth: 2 }}
            activeDot={{ r: 6, stroke: "var(--chart-surface)", strokeWidth: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function EvidenceList({ items, title, empty }: { items: HypothesisDetail["evidence"]; title: string; empty: string }) {
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">{title} ({items.length})</h3>
      {items.length === 0 ? <p className="text-sm text-zinc-500">{empty}</p> : (
        <ul className="space-y-2">
          {items.map((e) => (
            <li key={e.id} className="rounded border border-zinc-200 p-2 text-sm dark:border-zinc-800">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <Badge>{e.signal.type.replace(/_/g, " ")}</Badge>
                {e.signal.category === "early_signal" && <Badge tone="warn">Early Signal</Badge>}
                {e.independence_weight < 1 && <Badge tone="muted" >same origin ×{e.independence_weight}</Badge>}
                <span className="text-zinc-500">by {e.added_by} · {fmtDate(e.signal.observed_at)}</span>
                <span className="ml-auto tabular-nums text-zinc-600 dark:text-zinc-400" title="logit contribution after decay, reliability, independence and caps">
                  {e.contribution >= 0 ? "+" : ""}{e.contribution.toFixed(2)}
                </span>
              </div>
              <p className="mt-1">{e.signal.summary}</p>
              <p className="mt-0.5 text-xs text-zinc-500">{e.rationale}</p>
              <div className="mt-1 flex flex-wrap gap-3 text-xs text-zinc-500">
                <a className="text-sky-700 hover:underline dark:text-sky-400" href={e.signal.evidence_url} target="_blank" rel="noreferrer">evidence ↗</a>
                <span>relevance {e.relevance.toFixed(1)}</span>
                <span>source reliability {e.reliability.toFixed(2)}</span>
                <span>event confidence {e.signal.event_confidence.toFixed(2)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Detail({ id }: { id: number }) {
  const [d, err] = useLoad(() => api.get<HypothesisDetail>(`/hypotheses/${id}`), [id]);
  if (err) return <ErrorBox error={err} />;
  if (!d) return <Card><p className="text-sm text-zinc-500">Loading…</p></Card>;
  const support = d.evidence.filter((e) => e.stance === "supports");
  const against = d.evidence.filter((e) => e.stance === "contradicts");
  const neutral = d.evidence.filter((e) => e.stance === "neutral");
  return (
    <div className="space-y-3">
      <Card>
        <div className="text-xs text-zinc-500">{d.competitor} · {d.category} · prior {pct(d.prior)} · created {fmtDate(d.created_at)}
          {d.replay && <> · <Badge tone="synthetic">Replay</Badge></>}{d.synthetic && <> · <Badge tone="synthetic">Synthetic</Badge></>}</div>
        <h2 className="mt-1 text-lg font-semibold leading-snug">{d.statement}</h2>
        <div className="mt-2"><ScoreChip h={d} /></div>
        <div className="mt-2"><ConfidenceBar value={d.confidence} /></div>
      </Card>

      <Card title="Belief over time">
        <BeliefChart d={d} />
        <details className="mt-2 text-xs text-zinc-500">
          <summary className="cursor-pointer">Table view</summary>
          <table className="mt-1 w-full text-left">
            <thead><tr><th className="py-0.5">when</th><th>conf</th><th>Δ</th><th>reason</th></tr></thead>
            <tbody>{d.belief_history.map((b, i) => (
              <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                <td className="py-0.5 pr-2 whitespace-nowrap">{new Date(b.ts).toLocaleString()}</td>
                <td className="pr-2 tabular-nums">{pct(b.confidence)}</td><td className="pr-2 tabular-nums">{b.delta >= 0 ? "+" : ""}{pct(b.delta)}</td><td>{b.reason}</td>
              </tr>))}</tbody>
          </table>
        </details>
      </Card>

      <Card title="Evidence">
        <div className="grid gap-4 lg:grid-cols-2">
          <EvidenceList items={support} title="Supports" empty="No supporting evidence." />
          <EvidenceList items={against} title="Against" empty="No contradicting evidence found yet. The investigator looks for it each cycle." />
        </div>
        {neutral.length > 0 && <div className="mt-4"><EvidenceList items={neutral} title="Neutral / context" empty="" /></div>}
      </Card>

      <Card title={`Skeptic challenges (${d.challenges.length})`}>
        {d.challenges.length === 0 ? (
          <p className="text-sm text-zinc-500">Not challenged yet. The skeptic runs once a hypothesis reaches 0.60, before it can be raised to "likely" or alerted.</p>
        ) : (
          <ol className="space-y-3">
            {d.challenges.map((c) => (
              <li key={c.id} className="text-sm">
                <div className="flex flex-wrap items-center gap-2"><Badge tone={VERDICT_TONE[c.verdict] ?? "muted"}>{c.verdict.replace(/_/g, " ")}</Badge><span className="font-medium">{c.alternative}</span></div>
                <div className="mt-1 text-xs text-zinc-500"><span className="font-semibold">Test:</span> {c.discriminating_test}</div>
                {c.test_result && <div className="mt-0.5 whitespace-pre-line text-xs text-zinc-600 dark:text-zinc-400"><span className="font-semibold">Result:</span> {c.test_result}</div>}
              </li>
            ))}
          </ol>
        )}
      </Card>

      <Card title={`Investigations (${d.investigations.length})`}>
        {d.investigations.length === 0 ? <p className="text-sm text-zinc-500">No investigation yet. One runs when confidence sits in the uncertain band (0.35–0.80).</p> : (
          <div className="space-y-4">
            {d.investigations.map((inv) => (
              <div key={inv.id} className="text-sm">
                <div className="text-xs text-zinc-500">#{inv.id} · {new Date(inv.started_at).toLocaleString()} · {inv.actions.length} tool call(s) · {inv.tokens} tokens · stop: <span className="font-medium text-zinc-700 dark:text-zinc-300">{inv.stop_reason}</span></div>
                {inv.plan.length > 0 && <ol className="mt-1 list-decimal pl-5 text-zinc-700 dark:text-zinc-300">{inv.plan.map((p, i) => <li key={i}>{p}</li>)}</ol>}
                <ul className="mt-2 space-y-1 font-mono text-xs">
                  {inv.actions.map((a, i) => (
                    <li key={i} className="rounded bg-zinc-50 p-1.5 dark:bg-zinc-950">
                      <span className="text-zinc-900 dark:text-zinc-100">{a.tool}</span>({JSON.stringify(a.args)})
                      <div className="mt-0.5 whitespace-pre-line text-zinc-500">{a.result.slice(0, 400)}</div>
                    </li>
                  ))}
                </ul>
                {inv.findings.length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-xs">
                    {inv.findings.map((f, i) => (
                      <li key={i}>{f.dropped ? <Badge tone="bad">dropped</Badge> : <Badge tone="info">{f.stance}</Badge>} {f.summary} {f.why && <span className="text-zinc-500">({f.why})</span>}
                        {f.url && !f.dropped && <> <a className="text-sky-700 hover:underline dark:text-sky-400" href={f.url} target="_blank" rel="noreferrer">↗</a></>}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Predictions">
        {d.predictions.length === 0 ? (
          <>
            <p className="text-sm text-zinc-500">Falsifiable predictions are registered once confidence reaches 0.60. Proposed tests:</p>
            <ul className="mt-1 list-disc pl-5 text-sm">{d.testable_predictions.map((p, i) => <li key={i}>{p.claim} <span className="text-zinc-500">(within {p.horizon_days} days)</span></li>)}</ul>
          </>
        ) : (
          <ul className="space-y-1 text-sm">
            {d.predictions.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2">
                <Badge tone={p.outcome === "hit" ? "ok" : p.outcome === "miss" ? "bad" : "muted"}>{p.outcome}</Badge>
                <span>{p.claim}</span>
                <span className="text-xs text-zinc-500">by {fmtDate(p.resolve_by)} · made at {pct(p.confidence_at_creation)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function Hypotheses() {
  const [params, setParams] = useSearchParams();
  const [competitors] = useLoad(() => api.get<Competitor[]>("/competitors"));
  const [comp, setComp] = useState("");
  const [list, err] = useLoad(() => api.get<HypothesisSummary[]>(`/hypotheses${comp ? `?competitor=${comp}` : ""}`), [comp]);
  const selected = Number(params.get("id")) || list?.[0]?.id;
  const open = useMemo(() => list?.filter((h) => !["refuted", "stale"].includes(h.status)) ?? [], [list]);
  const closed = useMemo(() => list?.filter((h) => ["refuted", "stale"].includes(h.status)) ?? [], [list]);

  const item = (h: HypothesisSummary) => (
    <button key={h.id} onClick={() => setParams({ id: String(h.id) })}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${h.id === selected ? "border-zinc-900 bg-white dark:border-zinc-300 dark:bg-zinc-900" : "border-zinc-200 bg-white hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900"}`}>
      <div className="flex items-center justify-between gap-2 text-xs text-zinc-500"><span>{h.competitor} · {h.category}</span><span>{h.evidence_for} for · {h.evidence_against} against</span></div>
      <div className="mt-1 text-sm font-medium leading-snug">{h.statement}</div>
      <div className="mt-2 flex items-center gap-2"><Badge tone={STATUS_TONE[h.status]}>{h.status}</Badge><span className="text-xs tabular-nums">{pct(h.confidence)}</span><div className="flex-1"><ConfidenceBar value={h.confidence} /></div></div>
    </button>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Hypotheses</h1>
        <select className={`${inputCls} w-auto`} value={comp} onChange={(e) => { setComp(e.target.value); setParams({}); }} aria-label="Competitor">
          <option value="">All competitors</option>
          {competitors?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <p className="text-xs text-zinc-500">Scores are an uncalibrated heuristic (prior + independence-weighted evidence + skeptic verdicts), not validated probabilities.</p>
      {err && <ErrorBox error={err} />}
      {list && list.length === 0 && <Empty>No hypotheses yet. Run a cycle with an LLM key configured; the strategist proposes them from signals.</Empty>}
      {list && list.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
          <div className="space-y-2">
            {open.map(item)}
            {closed.length > 0 && <><div className="pt-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Closed</div>{closed.map(item)}</>}
          </div>
          <div className="min-w-0">{selected && <Detail id={selected} />}</div>
        </div>
      )}
    </div>
  );
}
