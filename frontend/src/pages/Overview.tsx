import { useState } from "react";
import { api, Health } from "../api/client";
import { Badge, Card, ErrorBox, Stat, btnCls, useLoad } from "../components/ui";

export default function Overview() {
  const [health, err, reload] = useLoad(() => api.get<Health>("/health"));
  const [ping, setPing] = useState<Health["llm"]["ping"] | null>(null);
  const [pinging, setPinging] = useState(false);

  async function testLlm() {
    setPinging(true);
    try {
      const h = await api.get<Health>("/health?llm_check=true");
      setPing(h.llm.ping ?? null);
    } catch (e) {
      setPing({ ok: false, error: String(e) });
    } finally {
      setPinging(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Overview</h1>
        <button className={btnCls} onClick={reload}>Refresh</button>
      </div>
      {err && <ErrorBox error={`Backend unreachable: ${err}. Is FastAPI running on :8000?`} />}
      {health && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Competitors" value={health.counts.competitors} />
            <Stat label="Signals" value={health.counts.signals} />
            <Stat label="Hypotheses" value={health.counts.hypotheses} />
            <Stat label="Agent runs" value={health.counts.agent_runs} />
          </div>
          <Card
            title="System"
            right={<button className={btnCls} onClick={testLlm} disabled={pinging}>{pinging ? "Testing…" : "Test LLM"}</button>}
          >
            <dl className="grid grid-cols-[8rem_1fr] gap-y-1 text-sm">
              <dt className="text-zinc-500">API / DB</dt>
              <dd><Badge tone="ok">{health.status}</Badge> <Badge tone="ok">db {health.db}</Badge></dd>
              <dt className="text-zinc-500">LLM provider</dt>
              <dd>
                {health.llm.provider}{" "}
                {health.llm.configured ? <Badge tone="ok">configured</Badge> : <Badge tone="warn">no API key in .env</Badge>}
              </dd>
              <dt className="text-zinc-500">Strong model</dt>
              <dd className="font-mono text-xs">{health.llm.strong}</dd>
              <dt className="text-zinc-500">Fast model</dt>
              <dd className="font-mono text-xs">{health.llm.fast}</dd>
              {ping && (
                <>
                  <dt className="text-zinc-500">LLM ping</dt>
                  <dd>{ping.ok ? <Badge tone="ok">ok: {ping.reply}</Badge> : <Badge tone="bad">{ping.error}</Badge>}</dd>
                </>
              )}
            </dl>
          </Card>
        </>
      )}
    </div>
  );
}
