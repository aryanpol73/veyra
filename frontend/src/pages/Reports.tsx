import { useState } from "react";
import { api, BriefMeta } from "../api/client";
import { Empty, ErrorBox, PageHeader, Skeleton, btnCls, useLoad } from "../components/ui";
import { IconReports } from "../components/icons";
import Markdown from "../components/Markdown";

const longDate = (d: string) => {
  const t = new Date(`${d}T00:00:00`);
  return isNaN(t.getTime()) ? d : t.toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
};

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
    <div className="space-y-5">
      <PageHeader
        index="07"
        title="Reports"
        description={<>Each brief covers what happened, why it matters and what to do, with evidence links and the skeptic's strongest alternative. Saved as Markdown in <code className="font-mono text-ink-2">data/reports/</code>.</>}
        actions={<button className={btnCls} onClick={generate} disabled={busy}><IconReports size={14} />{busy ? "Writing brief…" : "Generate brief (last 7 days)"}</button>}
      />
      {(err || genErr) && <ErrorBox error={(err ?? genErr)!} />}
      {list && list.length === 0 && <Empty>No briefs yet. Generate one above.</Empty>}
      {list && list.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[12rem_minmax(0,1fr)]">
          <nav aria-label="Briefs by date" className="min-w-0">
            <div className="mb-2 hidden font-mono text-[11px] uppercase tracking-[0.12em] text-muted lg:block">Archive · {list.length}</div>
            <ul className="scroll-thin flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:border-l lg:border-line lg:pb-0">
              {list.map((r) => {
                const active = r.date === day;
                return (
                  <li key={r.date} className="shrink-0">
                    <button onClick={() => setPicked(r.date)} aria-current={active ? "true" : undefined}
                      className={`relative flex h-10 w-full cursor-pointer items-center whitespace-nowrap rounded-[3px] px-3 text-left font-mono text-sm transition-colors lg:-ml-px lg:rounded-none lg:border-l-2 lg:pl-4 ${
                        active ? "bg-surface font-semibold text-ink lg:border-accent lg:bg-transparent" : "text-ink-2 hover:bg-surface-2 hover:text-ink lg:border-transparent lg:hover:bg-transparent"}`}>
                      <span className="tnum">{r.date}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <article className="min-w-0 rounded-[4px] border border-line bg-surface">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3 md:px-8">
              <span className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Brief · {day && longDate(day)}</span>
              <span className="font-mono text-[11px] text-muted">Markdown</span>
            </header>
            <div className="px-5 py-6 md:px-8 md:py-8">
              <div className="mx-auto max-w-[72ch]">
                {briefErr ? <ErrorBox error={briefErr} /> : brief ? <div key={brief.date} className="anim-route"><Markdown text={brief.markdown} size="md" /></div> : (
                  <div className="space-y-3"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-4/5" /></div>
                )}
              </div>
            </div>
          </article>
        </div>
      )}
    </div>
  );
}
