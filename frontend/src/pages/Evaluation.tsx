import { useEffect, useRef, useState } from "react";
import { CartesianGrid, ComposedChart, ErrorBar, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { api, CalibrationBin, EvalRun, EvalStatus } from "../api/client";
import { Badge, Card, Empty, ErrorBox, PageHeader, ProvenanceTag, Stat, btnCls, toneStyle, useLoad } from "../components/ui";
import { IconAlert, IconChevron, IconPlay } from "../components/icons";

const MODES = [
  { id: "masked", label: "Masked", hint: "company and product names replaced with neutral tokens in every prompt" },
  { id: "none", label: "Unmasked", hint: "real names in prompts; the model may recall outcomes (possibly contaminated)" },
  { id: "post_cutoff", label: "Post-cutoff", hint: "only events after the model's training cutoff" },
] as const;

const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "n/a" : x.toFixed(d));
const th = "py-2 pr-3 text-left font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-muted";
const td = "py-1.5 pr-3";

function CalibrationChart({ bins }: { bins: CalibrationBin[] }) {
  const pts = bins.filter((b) => b.n > 0 && b.mean_confidence !== null).map((b) => ({
    x: b.mean_confidence as number, y: b.observed_rate as number, n: b.n, bin: b.bin,
    err: b.wilson_95 ? [(b.observed_rate as number) - b.wilson_95[0], b.wilson_95[1] - (b.observed_rate as number)] : [0, 0],
  }));
  if (!pts.length) return <p className="text-sm text-muted">No hypotheses to calibrate yet.</p>;
  const tick = { fontSize: 11, fill: "var(--chart-ink)", fontFamily: "var(--font-mono)" };
  return (
    <figure>
      <figcaption className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-[11px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <svg width="14" height="14" aria-hidden="true"><line x1="7" y1="1" x2="7" y2="13" stroke="var(--series-1)" strokeWidth="1.25" /><line x1="4" y1="1" x2="10" y2="1" stroke="var(--series-1)" strokeWidth="1.25" /><line x1="4" y1="13" x2="10" y2="13" stroke="var(--series-1)" strokeWidth="1.25" /><circle cx="7" cy="7" r="3.5" fill="var(--series-1)" stroke="var(--chart-surface)" strokeWidth="1.5" /></svg>
          y: observed hit rate per bin, Wilson 95% interval
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden="true"><line x1="0" y1="4" x2="18" y2="4" stroke="var(--chart-ink)" strokeWidth="1" strokeDasharray="4 3" /></svg>
          perfect calibration
        </span>
      </figcaption>
      <div className="h-72 w-full" role="img" aria-label={`Calibration chart: ${pts.map((p) => `${p.bin} bin mean confidence ${fmt(p.x)}, observed ${fmt(p.y)}, n=${p.n}`).join("; ")}. Values are listed in the table below.`}>
        <ResponsiveContainer>
          <ComposedChart margin={{ top: 8, right: 16, bottom: 22, left: 0 }}>
            <CartesianGrid stroke="var(--chart-grid)" />
            <XAxis type="number" dataKey="x" domain={[0, 1]} ticks={[0, 0.4, 0.7, 1]} tick={tick} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }}
              label={{ value: "mean confidence in bin", position: "bottom", offset: 6, fontSize: 11, fill: "var(--chart-ink)", fontFamily: "var(--font-mono)" }} />
            <YAxis type="number" dataKey="y" domain={[0, 1]} ticks={[0, 0.5, 1]} width={40} tick={tick} tickLine={false} axisLine={false} />
            <Line data={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} dataKey="y" stroke="var(--chart-ink)" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false}
              label={false} legendType="none" />
            <Tooltip cursor={false} content={({ active, payload }) => {
              const p = active && payload?.[0]?.payload;
              if (!p || p.bin === undefined) return null;
              const b = bins.find((x) => x.bin === p.bin)!;
              return (
                <div className="rounded-[3px] border border-line-strong bg-surface p-2.5 font-mono text-xs text-ink-2 shadow-lg">
                  <div className="font-semibold text-ink">{b.bin} bin (n={b.n})</div>
                  <div>mean confidence {fmt(b.mean_confidence)}</div>
                  <div>observed hit rate {fmt(b.observed_rate)} ({b.hits}/{b.n})</div>
                  <div>Wilson 95% [{fmt(b.wilson_95?.[0])}, {fmt(b.wilson_95?.[1])}]</div>
                </div>
              );
            }} />
            <Scatter data={pts} fill="var(--series-1)" isAnimationActive={false}
              shape={(props: any) => <circle cx={props.cx} cy={props.cy} r={4.5} fill="var(--series-1)" stroke="var(--chart-surface)" strokeWidth={1.5} />}>
              <ErrorBar dataKey="err" direction="y" width={8} stroke="var(--series-1)" strokeWidth={1.25} />
            </Scatter>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function BinTable({ bins, withRange }: { bins: CalibrationBin[]; withRange?: boolean }) {
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[480px] text-xs">
        <thead><tr className="border-b border-line"><th className={th}>bin</th><th className={th}>n</th><th className={th}>hits</th><th className={th}>mean conf</th><th className={th}>observed</th><th className={th}>Wilson 95%</th></tr></thead>
        <tbody className="tnum font-mono text-ink-2">{bins.map((b) => (
          <tr key={b.bin} className="border-b border-line last:border-b-0">
            <td className={`${td} text-ink`}>{b.bin}{withRange && <span className="text-muted"> [{b.range[0]}, {b.range[1]})</span>}</td><td className={td}>{b.n}</td><td className={td}>{b.hits}</td>
            <td className={td}>{fmt(b.mean_confidence)}</td><td className={td}>{fmt(b.observed_rate)}</td>
            <td className={td}>{b.wilson_95 ? `[${fmt(b.wilson_95[0])}, ${fmt(b.wilson_95[1])}]` : "n/a"}</td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

function RunPanel({ mode, onDone }: { mode: string; onDone: () => void }) {
  const [st, setSt] = useState<EvalStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const was = useRef(false);
  const timer = useRef<number>();
  async function poll() {
    try {
      const s = await api.get<EvalStatus>("/eval/status");
      setSt(s);
      if (was.current && !s.running) onDone();
      was.current = s.running;
      timer.current = window.setTimeout(poll, s.running ? 3000 : 15000);
    } catch (e) { setErr(String(e)); }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { poll(); return () => window.clearTimeout(timer.current); }, []);
  async function run() {
    setErr(null);
    try { await api.post("/eval/run", { mode, synthetic: true }); was.current = true; window.clearTimeout(timer.current); poll(); }
    catch (e) { setErr(String((e as Error).message)); }
  }
  return (
    <Card
      title={<span className="inline-flex items-center gap-2"><span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${st?.running ? "anim-pulse bg-accent" : "bg-line-strong"}`} />Run the backtest</span>}
      right={<button className={btnCls} disabled={st?.running} onClick={run}><IconPlay />{st?.running ? `Running (${st.mode})…` : `Run ${mode} backtest`}</button>}
    >
      <p className="text-sm text-muted">Replays the same pipeline month by month over the frozen Wayback dataset in its own database. On the Groq free tier (8k tokens/min) a run takes 30-60 minutes.</p>
      {err && <div className="mt-3"><ErrorBox error={err} /></div>}
      {st?.log_tail && <pre className="scroll-thin mt-3 max-h-44 overflow-auto whitespace-pre-wrap rounded-[3px] border border-line bg-sunken p-2.5 font-mono text-xs leading-relaxed text-ink-2">{st.log_tail}</pre>}
    </Card>
  );
}

export default function Evaluation() {
  const [mode, setMode] = useState<string>("masked");
  const [run, err, reload] = useLoad(() => api.get<EvalRun>(`/eval/runs/latest?mode=${mode}`).catch((e) => {
    if (String(e).includes("404")) return null;
    throw e;
  }), [mode]);
  const m = run?.metrics;
  const c = run?.config ?? {};

  return (
    <div className="space-y-5">
      <PageHeader index="06" title="Evaluation" description="Backtest metrics and calibration for the hypothesis scores, replayed over a frozen historical dataset." />

      <div role="note" style={toneStyle("warn")} className="hatch-soft relative flex gap-3 rounded-[4px] border p-4 text-sm leading-relaxed">
        <IconAlert size={18} className="mt-0.5 shrink-0" />
        <div className="text-ink-2">
          <b className="font-mono text-xs font-semibold uppercase tracking-[0.1em]" style={{ color: "var(--warn)" }}>Pilot study.</b>{" "}
          A small, hand-labelled set of real events on 3 companies, replayed from Wayback captures of pricing,
          product and changelog pages plus blog feeds (no historical jobs, CT or news search). With this few events every number has
          wide uncertainty. Confidence scores remain an <b className="text-ink">uncalibrated heuristic</b> unless the calibration bins below sit near the diagonal
          with narrow intervals, which a sample this size cannot show.
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="inline-flex rounded-[4px] border border-line bg-surface p-0.5" role="tablist" aria-label="Contamination mode">
          {MODES.map((x) => (
            <button key={x.id} role="tab" aria-selected={mode === x.id} onClick={() => setMode(x.id)} title={x.hint}
              className={`h-9 cursor-pointer rounded-[3px] px-3.5 text-sm font-medium transition-colors ${mode === x.id ? "bg-ink text-bg" : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`}>
              {x.label}
            </button>
          ))}
        </div>
        <p className="font-mono text-xs text-muted">{MODES.find((x) => x.id === mode)?.hint}.</p>
      </div>

      <RunPanel mode={mode} onDone={reload} />
      {err && <ErrorBox error={err} />}
      {run === null && <Empty>No {mode} evaluation run yet. Start one above, or run <code className="font-mono text-ink-2">python -m app.eval.run_eval --mode {mode}</code>.</Empty>}

      {m && (
        <>
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
            <span className="text-ink-2">Run #{run!.id}</span>
            <span>{new Date(run!.created_at).toLocaleString()}</span>
            <span>window {c.window?.[0]?.slice(0, 10)} to {c.window?.[1]?.slice(0, 10)}</span>
            <span>{c.provider}/{c.model_strong}</span>
            <span className="tnum">{c.tokens?.toLocaleString()} tokens</span>
            {c.possibly_contaminated && <Badge tone="warn">possibly contaminated</Badge>}
            {c.degraded && <Badge tone="bad"><IconAlert size={11} />degraded: {c.llm_errors} LLM call(s) failed ({(c.llm_error_kinds ?? []).join(", ")})</Badge>}
            {c.classification === "rules" && <Badge tone="muted">signal classification: rules (live system uses the LLM)</Badge>}
            {c.agents === false && <Badge tone="warn">ingest only, no agents</Badge>}
            {mode === "post_cutoff" && <Badge tone="info">model cutoff {c.model_cutoff}: {m.n_events} of {c.events_total} events after it</Badge>}
          </div>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat index={0} label="Precision" value={fmt(m.precision)} sub={`n=${m.n_detected} detected`} />
            <Stat index={1} label="Recall" value={fmt(m.recall)} sub={`n=${m.n_events} events`} />
            <Stat index={2} label="Median lead time" value={m.lead_median === null ? "n/a" : `${m.lead_median.toFixed(0)} d`} sub="positive = early" />
            <Stat index={3} label="Brier · hypotheses" value={fmt(m.brier_hypotheses, 3)} sub="lower is better" />
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <Card title="Metrics" flush>
              <table className="w-full text-sm">
                <tbody className="[&_td]:px-4 [&_td]:py-2 [&_td:first-child]:text-ink-2 [&_td:last-child]:whitespace-nowrap [&_td:last-child]:text-right [&_td:last-child]:font-mono [&_td:last-child]:text-ink [&_td:last-child]:tabular-nums [&_tr]:border-b [&_tr]:border-line [&_tr:last-child]:border-b-0">
                  <tr><td>Ground-truth events in window</td><td>{m.n_events}</td></tr>
                  <tr><td>Hypotheses formed / detected (confidence ≥ {c.threshold})</td><td>{m.n_hypotheses} / {m.n_detected}</td></tr>
                  <tr><td>True positives</td><td>{m.true_positives}</td></tr>
                  <tr><td>Precision</td><td>{fmt(m.precision)}</td></tr>
                  <tr><td>Recall</td><td>{fmt(m.recall)}</td></tr>
                  <tr><td>False-positive rate (detected hypotheses matching no event)</td><td>{fmt(m.fp_rate)}</td></tr>
                  <tr><td>False alarms per competitor-month</td><td>{fmt(m.false_alarms_per_competitor_month)}</td></tr>
                  <tr><td>Lead times (days; positive = before announcement)</td><td className="!whitespace-normal">{m.lead_days?.length ? m.lead_days.join(", ") : "n/a"}</td></tr>
                  <tr><td>Early detections (lead &gt; 0)</td><td>{m.early_detections}</td></tr>
                  <tr><td>Brier score, hypotheses (final confidence vs matched)</td><td>{fmt(m.brier_hypotheses, 3)}</td></tr>
                  <tr><td>Brier score, predictions (n resolved = {m.n_predictions_resolved})</td><td>{fmt(m.brier_predictions, 3)}</td></tr>
                </tbody>
              </table>
            </Card>

            <Card title="Calibration (3 bins, Wilson 95% intervals)">
              <CalibrationChart bins={m.calibration ?? []} />
              <div className="mt-3 border-t border-line pt-1"><BinTable bins={m.calibration ?? []} withRange /></div>
              <p className="mt-3 text-xs leading-relaxed text-muted">Dashed line = perfect calibration. A "hit" is a hypothesis that matched a real labelled event. Bins use each hypothesis's final confidence (pre-declared).</p>
              {m.calibration_peak?.length > 0 && (
                <details className="mt-3 border-t border-line pt-2.5 text-xs">
                  <summary className="inline-flex cursor-pointer items-center gap-1 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-muted hover:text-ink">
                    <span className="chev transition-transform"><IconChevron size={12} /></span>Secondary view: peak confidence (added after the first run)
                  </summary>
                  <p className="mt-2 leading-relaxed text-muted">Recency decay lowers a hypothesis's final score even when it was right earlier in the window, so this view bins each hypothesis by its highest confidence instead. Brier (peak) <span className="tnum font-mono text-ink-2">{fmt(m.brier_hypotheses_peak, 3)}</span>.</p>
                  <div className="mt-2"><BinTable bins={m.calibration_peak} /></div>
                </details>
              )}
            </Card>
          </div>

          <Card title="Ground-truth events" flush>
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[680px] text-sm">
                <thead><tr className="border-b border-line"><th className={`${th} pl-4`}>result</th><th className={th}>announced</th><th className={th}>competitor</th><th className={th}>event</th><th className={th}>detected</th><th className={`${th} pr-4 text-right`}>lead</th></tr></thead>
                <tbody>{(m.events ?? []).map((e) => (
                  <tr key={e.id} className="border-b border-line align-top last:border-b-0 hover:bg-surface-2">
                    <td className="py-2.5 pl-4 pr-3">{e.is_true_positive ? <Badge tone="ok">✓ TP</Badge> : <Badge tone="muted">○ missed</Badge>}</td>
                    <td className="tnum whitespace-nowrap py-2.5 pr-3 font-mono text-xs text-ink-2">{e.public_date}</td>
                    <td className="py-2.5 pr-3 text-ink-2">{e.competitor}</td>
                    <td className="py-2.5 pr-3">
                      <a className="text-ink underline decoration-line-strong underline-offset-[3px] hover:decoration-accent" href={e.source_url} target="_blank" rel="noreferrer">{e.label} ↗</a>
                      {e.matched_statement && <div className="mt-1 text-xs text-muted"><span className="font-mono text-accent">H{e.matched_hypothesis_id}</span>: {e.matched_statement}</div>}
                    </td>
                    <td className="tnum whitespace-nowrap py-2.5 pr-3 font-mono text-xs text-ink-2">{e.detected_at ? e.detected_at.slice(0, 10) : "—"}</td>
                    <td className="tnum py-2.5 pr-4 text-right font-mono text-xs text-ink">{e.lead_days === null ? "—" : `${e.lead_days > 0 ? "+" : ""}${e.lead_days} d`}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          </Card>

          {m.synthetic_test && (
            <Card title="Synthetic injection test" right={<ProvenanceTag kind="synthetic" />}>
              <p className="flex flex-wrap items-center gap-2 text-sm text-ink">{m.synthetic_test.passed ? <Badge tone="ok">✓ passed</Badge> : <Badge tone="bad">✕ failed</Badge>} {m.synthetic_test.expectation}.</p>
              <p className="mt-2 text-xs leading-relaxed text-muted">
                Independent evidence: max confidence <span className="tnum font-mono text-ink-2">{fmt(m.synthetic_test.independent?.max_confidence)}</span> · one press release counted three times:
                {" "}<span className="tnum font-mono text-ink-2">{fmt(m.synthetic_test.one_press_release_x3?.max_confidence)}</span>. This tests the machinery, not real-world accuracy.
              </p>
            </Card>
          )}

          <Card title="Definitions and limitations">
            <ul className="space-y-1.5 pl-4 text-xs leading-relaxed text-ink-2 [&>li]:list-[square] marker:text-muted">
              <li>A hypothesis is <i>detected</i> at its first belief update with confidence ≥ {c.threshold}. It <i>matches</i> an event when one of the event's keywords (written before the replay ran) appears in its statement.</li>
              <li>A true positive is detected no later than {c.grace_days} days after the announcement; lead time = announcement date minus detection date.</li>
              <li>Replay steps are monthly, so lead times have roughly one-month resolution. Monthly Wayback captures can miss short-lived page changes.</li>
              <li>Ground truth was labelled from official feeds and pages by the project team; a single labeller and keyword matching both add error.</li>
              <li>Masking hides names, not facts: a model can still recognise a company from distinctive product details.</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
