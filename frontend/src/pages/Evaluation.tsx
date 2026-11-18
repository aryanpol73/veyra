import { useEffect, useRef, useState } from "react";
import { CartesianGrid, ComposedChart, ErrorBar, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { api, CalibrationBin, EvalRun, EvalStatus } from "../api/client";
import { Badge, Card, Empty, ErrorBox, Stat, btnCls, useLoad } from "../components/ui";

const MODES = [
  { id: "masked", label: "Masked", hint: "company and product names replaced with neutral tokens in every prompt" },
  { id: "none", label: "Unmasked", hint: "real names in prompts; the model may recall outcomes (possibly contaminated)" },
  { id: "post_cutoff", label: "Post-cutoff", hint: "only events after the model's training cutoff" },
] as const;

const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "n/a" : x.toFixed(d));

function CalibrationChart({ bins }: { bins: CalibrationBin[] }) {
  const pts = bins.filter((b) => b.n > 0 && b.mean_confidence !== null).map((b) => ({
    x: b.mean_confidence as number, y: b.observed_rate as number, n: b.n, bin: b.bin,
    err: b.wilson_95 ? [(b.observed_rate as number) - b.wilson_95[0], b.wilson_95[1] - (b.observed_rate as number)] : [0, 0],
  }));
  if (!pts.length) return <p className="text-sm text-zinc-500">No hypotheses to calibrate yet.</p>;
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        <ComposedChart margin={{ top: 8, right: 16, bottom: 18, left: 0 }}>
          <CartesianGrid stroke="var(--chart-grid)" />
          <XAxis type="number" dataKey="x" domain={[0, 1]} ticks={[0, 0.4, 0.7, 1]} tick={{ fontSize: 11, fill: "var(--chart-ink)" }}
            label={{ value: "mean confidence in bin", position: "bottom", offset: 2, fontSize: 11, fill: "var(--chart-ink)" }} />
          <YAxis type="number" dataKey="y" domain={[0, 1]} ticks={[0, 0.5, 1]} width={36} tick={{ fontSize: 11, fill: "var(--chart-ink)" }} />
          <Line data={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} dataKey="y" stroke="var(--chart-ink)" strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          <Tooltip content={({ active, payload }) => {
            const p = active && payload?.[0]?.payload;
            if (!p || p.bin === undefined) return null;
            const b = bins.find((x) => x.bin === p.bin)!;
            return (
              <div className="rounded border border-zinc-200 bg-white p-2 text-xs shadow dark:border-zinc-700 dark:bg-zinc-900">
                <div className="font-semibold">{b.bin} bin (n={b.n})</div>
                <div>mean confidence {fmt(b.mean_confidence)}</div>
                <div>observed hit rate {fmt(b.observed_rate)} ({b.hits}/{b.n})</div>
                <div>Wilson 95% [{fmt(b.wilson_95?.[0])}, {fmt(b.wilson_95?.[1])}]</div>
              </div>
            );
          }} />
          <Scatter data={pts} fill="var(--series-1)" isAnimationActive={false}
            shape={(props: any) => <circle cx={props.cx} cy={props.cy} r={5} fill="var(--series-1)" stroke="var(--chart-surface)" strokeWidth={2} />}>
            <ErrorBar dataKey="err" direction="y" width={6} stroke="var(--series-1)" strokeWidth={2} />
          </Scatter>
        </ComposedChart>
      </ResponsiveContainer>
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
    <Card title="Run the backtest" right={<button className={btnCls} disabled={st?.running} onClick={run}>{st?.running ? `Running (${st.mode})…` : `Run ${mode} backtest`}</button>}>
      <p className="text-xs text-zinc-500">Replays the same pipeline month by month over the frozen Wayback dataset in its own database. On the Groq free tier (8k tokens/min) a run takes 30-60 minutes.</p>
      {err && <ErrorBox error={err} />}
      {st?.log_tail && <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-zinc-50 p-2 text-xs dark:bg-zinc-950">{st.log_tail}</pre>}
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
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Evaluation</h1>
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
        <b>Pilot study.</b> A small, hand-labelled set of real events on 3 companies, replayed from Wayback captures of pricing,
        product and changelog pages plus blog feeds (no historical jobs, CT or news search). With this few events every number has
        wide uncertainty. Confidence scores remain an <b>uncalibrated heuristic</b> unless the calibration bins below sit near the diagonal
        with narrow intervals, which a sample this size cannot show.
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Contamination mode">
        {MODES.map((x) => (
          <button key={x.id} role="tab" aria-selected={mode === x.id} onClick={() => setMode(x.id)}
            className={`rounded border px-3 py-1.5 text-sm ${mode === x.id ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900" : "border-zinc-300 dark:border-zinc-700"}`}
            title={x.hint}>{x.label}</button>
        ))}
      </div>
      <p className="text-xs text-zinc-500">{MODES.find((x) => x.id === mode)?.hint}.</p>

      <RunPanel mode={mode} onDone={reload} />
      {err && <ErrorBox error={err} />}
      {run === null && <Empty>No {mode} evaluation run yet. Start one above, or run <code>python -m app.eval.run_eval --mode {mode}</code>.</Empty>}

      {m && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            <span>Run #{run!.id} · {new Date(run!.created_at).toLocaleString()} · window {c.window?.[0]?.slice(0, 10)} to {c.window?.[1]?.slice(0, 10)}</span>
            <span>· {c.provider}/{c.model_strong} · {c.tokens?.toLocaleString()} tokens</span>
            {c.possibly_contaminated && <Badge tone="warn">possibly contaminated</Badge>}
            {c.degraded && <Badge tone="bad">degraded: {c.llm_errors} LLM call(s) failed ({(c.llm_error_kinds ?? []).join(", ")})</Badge>}
            {c.classification === "rules" && <Badge tone="muted" >signal classification: rules (live system uses the LLM)</Badge>}
            {c.agents === false && <Badge tone="warn">ingest only, no agents</Badge>}
            {mode === "post_cutoff" && <Badge tone="info">model cutoff {c.model_cutoff}: {m.n_events} of {c.events_total} events after it</Badge>}
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label={`Precision (n=${m.n_detected})`} value={fmt(m.precision)} />
            <Stat label={`Recall (n=${m.n_events})`} value={fmt(m.recall)} />
            <Stat label="Median lead time" value={m.lead_median === null ? "n/a" : `${m.lead_median.toFixed(0)} d`} />
            <Stat label="Brier (hypotheses)" value={fmt(m.brier_hypotheses, 3)} />
          </div>

          <Card title="Metrics">
            <table className="w-full text-sm">
              <tbody className="[&_td]:py-1 [&_td:first-child]:text-zinc-500 [&_td:last-child]:text-right [&_td:last-child]:tabular-nums">
                <tr><td>Ground-truth events in window</td><td>{m.n_events}</td></tr>
                <tr><td>Hypotheses formed / detected (confidence ≥ {c.threshold})</td><td>{m.n_hypotheses} / {m.n_detected}</td></tr>
                <tr><td>True positives</td><td>{m.true_positives}</td></tr>
                <tr><td>Precision</td><td>{fmt(m.precision)}</td></tr>
                <tr><td>Recall</td><td>{fmt(m.recall)}</td></tr>
                <tr><td>False-positive rate (detected hypotheses matching no event)</td><td>{fmt(m.fp_rate)}</td></tr>
                <tr><td>False alarms per competitor-month</td><td>{fmt(m.false_alarms_per_competitor_month)}</td></tr>
                <tr><td>Lead times (days; positive = before announcement)</td><td>{m.lead_days.length ? m.lead_days.join(", ") : "n/a"}</td></tr>
                <tr><td>Early detections (lead &gt; 0)</td><td>{m.early_detections}</td></tr>
                <tr><td>Brier score, hypotheses (final confidence vs matched)</td><td>{fmt(m.brier_hypotheses, 3)}</td></tr>
                <tr><td>Brier score, predictions (n resolved = {m.n_predictions_resolved})</td><td>{fmt(m.brier_predictions, 3)}</td></tr>
              </tbody>
            </table>
          </Card>

          <Card title="Calibration (3 bins, Wilson 95% intervals)">
            <CalibrationChart bins={m.calibration} />
            <table className="mt-2 w-full text-xs">
              <thead className="text-left text-zinc-500"><tr><th>bin</th><th>n</th><th>hits</th><th>mean conf</th><th>observed</th><th>Wilson 95%</th></tr></thead>
              <tbody className="tabular-nums">{m.calibration.map((b) => (
                <tr key={b.bin} className="border-t border-zinc-200 dark:border-zinc-800"><td className="py-0.5">{b.bin} [{b.range[0]}, {b.range[1]})</td><td>{b.n}</td><td>{b.hits}</td><td>{fmt(b.mean_confidence)}</td><td>{fmt(b.observed_rate)}</td>
                  <td>{b.wilson_95 ? `[${fmt(b.wilson_95[0])}, ${fmt(b.wilson_95[1])}]` : "n/a"}</td></tr>))}</tbody>
            </table>
            <p className="mt-2 text-xs text-zinc-500">Dashed line = perfect calibration. A "hit" is a hypothesis that matched a real labelled event.</p>
          </Card>

          <Card title="Ground-truth events">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="text-left text-xs text-zinc-500"><tr><th></th><th>announced</th><th>competitor</th><th>event</th><th>detected</th><th className="text-right">lead</th></tr></thead>
                <tbody>{m.events.map((e) => (
                  <tr key={e.id} className="border-t border-zinc-200 align-top dark:border-zinc-800">
                    <td className="py-1 pr-2">{e.is_true_positive ? <Badge tone="ok">TP</Badge> : <Badge tone="muted">missed</Badge>}</td>
                    <td className="whitespace-nowrap pr-2">{e.public_date}</td>
                    <td className="pr-2">{e.competitor}</td>
                    <td className="pr-2"><a className="hover:underline" href={e.source_url} target="_blank" rel="noreferrer">{e.label} ↗</a>
                      {e.matched_statement && <div className="text-xs text-zinc-500">H{e.matched_hypothesis_id}: {e.matched_statement}</div>}</td>
                    <td className="whitespace-nowrap pr-2">{e.detected_at ? e.detected_at.slice(0, 10) : "—"}</td>
                    <td className="text-right tabular-nums">{e.lead_days === null ? "—" : `${e.lead_days > 0 ? "+" : ""}${e.lead_days} d`}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          </Card>

          {m.synthetic_test && (
            <Card title="Synthetic injection test" right={<Badge tone="synthetic">Synthetic</Badge>}>
              <p className="text-sm">{m.synthetic_test.passed ? <Badge tone="ok">passed</Badge> : <Badge tone="bad">failed</Badge>} {m.synthetic_test.expectation}.</p>
              <p className="mt-1 text-xs text-zinc-500">
                Independent evidence: max confidence {fmt(m.synthetic_test.independent?.max_confidence)} · one press release counted three times:
                {" "}{fmt(m.synthetic_test.one_press_release_x3?.max_confidence)}. This tests the machinery, not real-world accuracy.
              </p>
            </Card>
          )}

          <Card title="Definitions and limitations">
            <ul className="list-disc space-y-1 pl-5 text-xs text-zinc-600 dark:text-zinc-400">
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
