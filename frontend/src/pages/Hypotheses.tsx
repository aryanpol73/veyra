import { CSSProperties, ReactNode, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Competitor, HypothesisDetail, HypothesisSummary } from "../api/client";
import {
  Badge, Card, ConfidenceGauge, ConfidenceRing, ContributionBar, Empty, ErrorBox, ExtLink, Eyebrow, PageHeader, ProvenanceTag, Skeleton,
  StanceMark, StatusTag, Tone, inputCls, useLoad,
} from "../components/ui";
import { IconChevron, IconTool } from "../components/icons";

const VERDICT_TONE: Record<string, Tone> = {
  alternative_refuted: "ok", alternative_supported: "bad", inconclusive: "muted", pending: "warn",
};
const fmtDate = (d: string) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const pct = (x: number) => x.toFixed(2);

function Meta({ k, v }: { k: string; v: ReactNode }) {
  return <span className="whitespace-nowrap"><span className="text-muted">{k}</span> <span className="tnum text-ink-2">{v}</span></span>;
}

function BeliefChart({ d }: { d: HypothesisDetail }) {
  const data = d.belief_history.map((b, i) => ({ i, t: new Date(b.ts).getTime(), confidence: b.confidence, reason: b.reason, delta: b.delta }));
  if (data.length < 2) return <p className="text-sm text-muted">Only one belief update so far; the timeline fills in as cycles run.</p>;
  const sameDay = new Date(data[0].t).toDateString() === new Date(data[data.length - 1].t).toDateString();
  const tick = (i: number) => sameDay ? `update ${i + 1}` : new Date(data[i]?.t ?? 0).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return (
    <figure>
      <figcaption className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden="true"><line x1="0" y1="4" x2="18" y2="4" stroke="var(--series-1)" strokeWidth="1.5" /><circle cx="9" cy="4" r="2.5" fill="var(--series-1)" /></svg>
          confidence after each update (heuristic)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden="true"><line x1="0" y1="4" x2="18" y2="4" stroke="var(--chart-ink)" strokeWidth="1" strokeDasharray="3 3" /></svg>
          status thresholds
        </span>
      </figcaption>
      <div className="h-56 w-full" style={{ color: "var(--chart-ink)" }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 64, bottom: 4, left: 0 }}>
            <ReferenceArea y1={0.7} y2={1} fill="var(--series-1)" fillOpacity={0.04} ifOverflow="hidden" />
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="0" vertical={false} />
            <XAxis dataKey="i" tick={{ fontSize: 11, fill: "var(--chart-ink)", fontFamily: "var(--font-mono)" }} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }}
              tickFormatter={tick} minTickGap={16} />
            <YAxis domain={[0, 1]} ticks={[0, 0.4, 0.7, 0.9, 1]} width={36} tick={{ fontSize: 11, fill: "var(--chart-ink)", fontFamily: "var(--font-mono)" }} tickLine={false} axisLine={false} />
            {[{ y: 0.4, l: "plausible" }, { y: 0.7, l: "likely" }, { y: 0.9, l: "confirmed" }].map((r) => (
              <ReferenceLine key={r.y} y={r.y} stroke="var(--chart-ink)" strokeOpacity={0.5} strokeDasharray="3 3"
                label={{ value: r.l, position: "right", fontSize: 10, fill: "var(--chart-ink)", fontFamily: "var(--font-mono)" }} />
            ))}
            <Tooltip
              cursor={{ stroke: "var(--chart-ink)", strokeWidth: 1, strokeDasharray: "2 2" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof data)[number];
                return (
                  <div className="max-w-xs rounded-[6px] border border-line-strong bg-surface p-2.5 text-xs shadow-lg">
                    <div className="tnum font-mono font-semibold text-ink">{pct(p.confidence)} <span className="text-muted">({p.delta >= 0 ? "+" : ""}{pct(p.delta)})</span></div>
                    <div className="font-mono text-[11px] text-muted">{new Date(p.t).toLocaleString()}</div>
                    <div className="mt-1 text-ink-2">{p.reason}</div>
                  </div>
                );
              }}
            />
            <Line type="linear" dataKey="confidence" stroke="var(--series-1)" strokeWidth={1.5} isAnimationActive={false}
              dot={{ r: 3, fill: "var(--series-1)", stroke: "var(--chart-surface)", strokeWidth: 1.5 }}
              activeDot={{ r: 5, stroke: "var(--chart-surface)", strokeWidth: 2 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function EvidenceList({ items, title, empty, stance }: { items: HypothesisDetail["evidence"]; title: string; empty: string; stance: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-2.5 flex items-center gap-2 border-b border-line pb-2">
        <StanceMark stance={stance} />
        <Eyebrow className="text-ink-2">{title}</Eyebrow>
        <span className="tnum ml-auto font-mono text-[11px] text-muted">{items.length} item{items.length === 1 ? "" : "s"}</span>
      </div>
      {items.length === 0 ? <p className="py-2 text-sm text-muted">{empty}</p> : (
        <ul className="space-y-2">
          {items.map((e, i) => (
            <li key={e.id} className="anim-rise relative rounded-[6px] border border-line bg-surface-2 py-3 pl-4 pr-3" style={{ "--i": i } as CSSProperties}>
              <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-[3px] ${e.stance === "neutral" ? "bg-line-strong" : ""}`}
                style={e.stance !== "neutral" ? { background: `var(--${e.stance === "supports" ? "ok" : "bad"})` } : undefined} />
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge>{e.signal.type.replace(/_/g, " ")}</Badge>
                {e.signal.category === "early_signal" && <ProvenanceTag kind="early" />}
                {e.independence_weight < 1 && <Badge tone="muted">same origin ×{e.independence_weight}</Badge>}
                <span className="ml-auto"><ContributionBar value={e.contribution} /></span>
              </div>
              <p className="mt-2 text-sm leading-snug text-ink">{e.signal.summary}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{e.rationale}</p>
              <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-2 font-mono text-[11px]">
                <ExtLink href={e.signal.evidence_url}>evidence</ExtLink>
                <Meta k="relevance" v={e.relevance.toFixed(1)} />
                <Meta k="source reliability" v={e.reliability.toFixed(2)} />
                <Meta k="event confidence" v={e.signal.event_confidence.toFixed(2)} />
                <span className="text-muted">by {e.added_by} · {fmtDate(e.signal.observed_at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-4">
      <div className="rounded-[12px] border border-line bg-surface p-5"><Skeleton className="h-3 w-1/2" /><Skeleton className="mt-3 h-6 w-full" /><Skeleton className="mt-2 h-6 w-2/3" /><Skeleton className="mt-6 h-3 w-full" /></div>
      <div className="rounded-[12px] border border-line bg-surface p-5"><Skeleton className="h-48 w-full" /></div>
    </div>
  );
}

function Detail({ id }: { id: number }) {
  const [d, err] = useLoad(() => api.get<HypothesisDetail>(`/hypotheses/${id}`), [id]);
  if (err) return <ErrorBox error={err} />;
  if (!d) return <DetailSkeleton />;
  const support = d.evidence.filter((e) => e.stance === "supports");
  const against = d.evidence.filter((e) => e.stance === "contradicts");
  const neutral = d.evidence.filter((e) => e.stance === "neutral");
  return (
    <div key={d.id} className="anim-route space-y-4">
      {/* dossier header */}
      <section className="relative overflow-hidden rounded-[12px] border border-line bg-surface">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-5 py-2.5 font-mono text-[11px]">
          <span className="font-semibold text-accent">H{d.id}</span>
          <span className="text-ink-2">{d.competitor}</span>
          <span className="text-muted">{d.category}</span>
          <Meta k="prior" v={pct(d.prior)} />
          <span className="text-muted">created {fmtDate(d.created_at)}</span>
          {(d.replay || d.synthetic) && <span className="flex gap-1.5">{d.replay && <ProvenanceTag kind="replay" />}{d.synthetic && <ProvenanceTag kind="synthetic" />}</span>}
        </div>
        <div className="grid gap-6 p-5 md:grid-cols-[minmax(0,1fr)_15rem]">
          <div className="min-w-0">
            <h2 className="font-display text-xl font-semibold leading-snug tracking-[-0.015em] text-ink md:text-[24px]">{d.statement}</h2>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <StatusTag status={d.status} />
              <span className="font-mono text-[11px] text-muted" title="Not a validated probability until the Evaluation page shows calibration">{d.score_label}</span>
            </div>
          </div>
          <div className="min-w-0 md:border-l md:border-line md:pl-6">
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Confidence</span>
              <span className="font-mono text-[11px] uppercase text-ink-2">{d.band}</span>
            </div>
            <div className="mt-3 flex justify-center"><ConfidenceRing value={d.confidence} status={d.status} size={112} /></div>
            <div className="mt-4"><ConfidenceGauge value={d.confidence} prior={d.prior} size="lg" /></div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-muted">
              <span className="inline-flex items-center gap-1.5 whitespace-nowrap"><span className="inline-block h-0 w-0 border-x-[4px] border-b-[5px] border-x-transparent border-b-muted" aria-hidden="true" />prior {pct(d.prior)}</span>
              <span className="inline-flex items-center gap-1.5 whitespace-nowrap"><span className="hatch inline-block h-2 w-3" aria-hidden="true" />uncalibrated</span>
            </div>
          </div>
        </div>
      </section>

      <Card title="Belief over time">
        <BeliefChart d={d} />
        <details className="group mt-3 border-t border-line pt-2.5 text-xs">
          <summary className="inline-flex cursor-pointer items-center gap-1 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-muted hover:text-ink"><span className="chev transition-transform"><IconChevron size={12} /></span>Table view</summary>
          <div className="scroll-thin mt-2 overflow-x-auto">
            <table className="w-full min-w-[520px] text-left">
              <thead className="font-mono text-[11px] text-muted"><tr><th className="py-1 pr-3 font-medium">when</th><th className="pr-3 font-medium">conf</th><th className="pr-3 font-medium">Δ</th><th className="font-medium">reason</th></tr></thead>
              <tbody>{d.belief_history.map((b, i) => (
                <tr key={i} className="border-t border-line align-top text-ink-2">
                  <td className="tnum whitespace-nowrap py-1.5 pr-3 font-mono">{new Date(b.ts).toLocaleString()}</td>
                  <td className="tnum pr-3 font-mono text-ink">{pct(b.confidence)}</td><td className="tnum pr-3 font-mono">{b.delta >= 0 ? "+" : ""}{pct(b.delta)}</td><td className="py-1.5">{b.reason}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </details>
      </Card>

      <Card title="Evidence ledger" right={<span className="font-mono text-[11px] text-muted">contribution = logit after decay, reliability, independence, caps</span>}>
        <div className="grid gap-5 xl:grid-cols-2">
          <EvidenceList items={support} title="Supports" stance="supports" empty="No supporting evidence." />
          <EvidenceList items={against} title="Against" stance="contradicts" empty="No contradicting evidence found yet. The investigator looks for it each cycle." />
        </div>
        {neutral.length > 0 && <div className="mt-5"><EvidenceList items={neutral} title="Neutral / context" stance="neutral" empty="" /></div>}
      </Card>

      <Card title={`Skeptic challenges (${d.challenges.length})`}>
        {d.challenges.length === 0 ? (
          <p className="text-sm text-muted">Not challenged yet. The skeptic runs once a hypothesis reaches 0.60, before it can be raised to "likely" or alerted.</p>
        ) : (
          <ol className="space-y-3">
            {d.challenges.map((c, i) => (
              <li key={c.id} className="grid gap-x-4 gap-y-2 rounded-[6px] border border-line bg-surface-2 p-3.5 sm:grid-cols-[auto_minmax(0,1fr)]">
                <div className="flex items-start gap-2 sm:flex-col">
                  <span className="tnum font-mono text-[11px] text-muted">Alt {String(i + 1).padStart(2, "0")}</span>
                  <Badge tone={VERDICT_TONE[c.verdict] ?? "muted"}>{c.verdict.replace(/_/g, " ")}</Badge>
                </div>
                <div className="min-w-0 space-y-1.5 text-sm">
                  <p className="font-medium leading-snug text-ink">{c.alternative}</p>
                  <p className="text-xs leading-relaxed text-ink-2"><span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Test</span> {c.discriminating_test}</p>
                  {c.test_result && <p className="whitespace-pre-line text-xs leading-relaxed text-ink-2"><span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted">Result</span> {c.test_result}</p>}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>

      <Card title={`Investigations (${d.investigations.length})`}>
        {d.investigations.length === 0 ? <p className="text-sm text-muted">No investigation yet. One runs when confidence sits in the uncertain band (0.35–0.80).</p> : (
          <div className="space-y-6">
            {d.investigations.map((inv) => (
              <div key={inv.id} className="min-w-0 text-sm">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
                  <span className="font-semibold text-ink">#{inv.id}</span>
                  <span>{new Date(inv.started_at).toLocaleString()}</span>
                  <span>{inv.actions.length} tool call(s)</span>
                  <span className="tnum">{inv.tokens} tokens</span>
                  <span>stop: <span className="font-medium text-ink-2">{inv.stop_reason}</span></span>
                </div>
                {inv.plan.length > 0 && <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-ink-2 marker:font-mono marker:text-muted">{inv.plan.map((p, i) => <li key={i}>{p}</li>)}</ol>}
                <ul className="mt-3 space-y-1.5 border-l border-line pl-3 font-mono text-xs">
                  {inv.actions.map((a, i) => (
                    <li key={i} className="min-w-0 rounded-[6px] bg-sunken p-2 [overflow-wrap:anywhere]">
                      <span className="inline-flex items-center gap-1 font-medium text-accent"><IconTool size={12} />{a.tool}</span><span className="text-ink-2">({JSON.stringify(a.args)})</span>
                      <div className="mt-1 whitespace-pre-line text-muted">{a.result.slice(0, 400)}</div>
                    </li>
                  ))}
                </ul>
                {inv.findings.length > 0 && (
                  <ul className="mt-3 space-y-1.5 text-xs">
                    {inv.findings.map((f, i) => (
                      <li key={i} className="flex flex-wrap items-baseline gap-1.5 text-ink-2">
                        {f.dropped ? <Badge tone="bad">dropped</Badge> : <Badge tone="info">{f.stance}</Badge>} <span className="min-w-0">{f.summary}</span> {f.why && <span className="text-muted">({f.why})</span>}
                        {f.url && !f.dropped && <ExtLink href={f.url}>source</ExtLink>}
                      </li>
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
            <p className="text-sm text-muted">Falsifiable predictions are registered once confidence reaches 0.60. Proposed tests:</p>
            <ul className="mt-2 space-y-1 pl-5 text-sm text-ink-2 [&>li]:list-[square] marker:text-muted">{d.testable_predictions.map((p, i) => <li key={i}>{p.claim} <span className="font-mono text-[11px] text-muted">(within {p.horizon_days} days)</span></li>)}</ul>
          </>
        ) : (
          <ul className="divide-y divide-line text-sm">
            {d.predictions.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2 py-2 first:pt-0 last:pb-0">
                <Badge tone={p.outcome === "hit" ? "ok" : p.outcome === "miss" ? "bad" : "muted"}>{p.outcome}</Badge>
                <span className="min-w-0 flex-1 text-ink">{p.claim}</span>
                <span className="tnum font-mono text-[11px] text-muted">by {fmtDate(p.resolve_by)} · made at {pct(p.confidence_at_creation)}</span>
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

  const item = (h: HypothesisSummary, i: number) => {
    const active = h.id === selected;
    return (
      <li key={h.id} className="anim-rise" style={{ "--i": Math.min(i, 12) } as CSSProperties}>
        <button onClick={() => setParams({ id: String(h.id) })} aria-current={active ? "true" : undefined}
          className={`relative w-full cursor-pointer rounded-[12px] border p-3.5 text-left transition-colors ${active ? "border-[color-mix(in_srgb,var(--accent)_45%,var(--line))] bg-surface shadow-[0_0_0_1px_color-mix(in_srgb,var(--accent)_20%,transparent),0_8px_30px_-12px_var(--glow)]" : "border-line bg-surface/90 hover:border-line-strong hover:bg-surface-2"}`}>
          <span aria-hidden="true" className={`absolute inset-y-3 left-0 w-[3px] rounded-r bg-accent transition-transform duration-200 ${active ? "scale-y-100" : "scale-y-0"}`} />
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px]">
            <span className={active ? "font-semibold text-accent" : "text-muted"}>H{h.id}</span>
            <span className="text-ink-2">{h.competitor}</span>
            <span className="text-muted">{h.category}</span>
            {h.replay && <ProvenanceTag kind="replay" />}{h.synthetic && <ProvenanceTag kind="synthetic" />}
          </div>
          <div className="mt-2 flex items-start gap-3">
            <ConfidenceRing value={h.confidence} status={h.status} size={50} />
            <div className="min-w-0 flex-1 text-sm font-medium leading-snug text-ink">{h.statement}</div>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
            <StatusTag status={h.status} />
            <span><span className="font-semibold" style={{ color: "var(--ok)" }}>+</span> {h.evidence_for} for</span>
            <span><span className="font-semibold" style={{ color: "var(--bad)" }}>−</span> {h.evidence_against} against</span>
          </div>
        </button>
      </li>
    );
  };

  return (
    <div className="space-y-5">
      <PageHeader
        index="02"
        title="Hypotheses"
        description={<>Scores are an <b className="font-semibold text-ink-2">uncalibrated heuristic</b> (prior + independence-weighted evidence + skeptic verdicts), not validated probabilities.</>}
        actions={
          <label className="flex items-center gap-2">
            <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">Competitor</span>
            <select className={`${inputCls} w-auto min-w-44`} value={comp} onChange={(e) => { setComp(e.target.value); setParams({}); }}>
              <option value="">All competitors</option>
              {competitors?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        }
      />
      {err && <ErrorBox error={err} />}
      {!list && !err && (
        <div className="grid gap-5 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="rounded-[12px] border border-line bg-surface p-3.5"><Skeleton className="h-3 w-1/2" /><Skeleton className="mt-2.5 h-4 w-full" /><Skeleton className="mt-3 h-2 w-full" /></div>)}</div>
          <DetailSkeleton />
        </div>
      )}
      {list && list.length === 0 && <Empty>No hypotheses yet. Run a cycle with an LLM key configured; the strategist proposes them from signals.</Empty>}
      {list && list.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <nav aria-label="Hypotheses" className="lg:sticky lg:top-6 lg:max-h-[calc(100dvh-3rem)] lg:self-start lg:overflow-y-auto lg:pr-1 scroll-thin">
            <div className="mb-2 flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.12em] text-muted"><span>Open</span><span className="tnum">{open.length}</span></div>
            <ul className="space-y-2">{open.map(item)}</ul>
            {closed.length > 0 && <>
              <div className="mb-2 mt-5 flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.12em] text-muted"><span>Closed</span><span className="tnum">{closed.length}</span></div>
              <ul className="space-y-2 opacity-90">{closed.map((h, i) => item(h, open.length + i))}</ul>
            </>}
          </nav>
          <div className="min-w-0">{selected && <Detail id={selected} />}</div>
        </div>
      )}
    </div>
  );
}
