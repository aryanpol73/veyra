import { useState } from "react";
import { api, BriefMeta } from "../api/client";
import { Card, Empty, ErrorBox, btnCls, useLoad } from "../components/ui";
import Markdown from "../components/Markdown";

export default function Reports() {
  const [list, err, reload] = useLoad(() => api.get<BriefMeta[]>("/reports"));
  const [picked, setPicked] = useState<string | null>(null);
  const day = picked ?? list?.[0]?.date ?? null;
  const [brief, briefErr] = useLoad(() => (day ? api.get<{ date: string; markdown: string }>(`/reports/${day}`) : Promise.resolve(null)), [day]);
  const [busy, setBusy] = useState(false);
  const [genErr, setGenErr] = useState<string | null>(null);

  async function generate() {
    setBusy(true);
    setGenErr(null);
    try {
      const r = await api.post<{ date: string }>("/reports/daily", { since_hours: 24 * 7 });
      setPicked(r.date);
      reload();
    } catch (e) {
      setGenErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Reports</h1>
        <button className={btnCls} onClick={generate} disabled={busy}>{busy ? "Writing brief…" : "Generate brief (last 7 days)"}</button>
      </div>
      <p className="text-xs text-zinc-500">Each brief covers what happened, why it matters and what to do, with evidence links and the skeptic's strongest alternative. Saved as Markdown in <code>data/reports/</code>.</p>
      {(err || genErr) && <ErrorBox error={(err ?? genErr)!} />}
      {list && list.length === 0 && <Empty>No briefs yet. Generate one above.</Empty>}
      {list && list.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[10rem_1fr]">
          <ul className="flex gap-1 overflow-x-auto lg:flex-col">
            {list.map((r) => (
              <li key={r.date}>
                <button onClick={() => setPicked(r.date)}
                  className={`w-full whitespace-nowrap rounded px-3 py-1.5 text-left text-sm ${r.date === day ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}>
                  {r.date}
                </button>
              </li>
            ))}
          </ul>
          <Card>{briefErr ? <ErrorBox error={briefErr} /> : brief ? <Markdown text={brief.markdown} /> : <p className="text-sm text-zinc-500">Loading…</p>}</Card>
        </div>
      )}
    </div>
  );
}
