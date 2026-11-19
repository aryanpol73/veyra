import { CSSProperties, FormEvent, ReactNode, useState } from "react";
import { api, Competitor, CompetitorIn } from "../api/client";
import { Badge, Card, Empty, ErrorBox, PageHeader, ProvenanceTag, Skeleton, Tone, btnCls, btnSecondaryCls, inputCls, useLoad } from "../components/ui";
import { IconExternal, IconPlus, IconSearch, IconTrash } from "../components/icons";

const TONE: Record<string, Tone> = { page: "info", jobs: "ok", news: "muted", early_signal: "warn" };

const blank: CompetitorIn = { name: "", domain: "", pricing_url: "", product_urls: [], careers_provider: null, careers_token: "", news_query: "" };

function Field({ label, children, wide, hint }: { label: string; children: ReactNode; wide?: boolean; hint?: ReactNode }) {
  return (
    <label className={`flex min-w-0 flex-col gap-1 ${wide ? "md:col-span-2" : ""}`}>
      <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-2">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

export default function Competitors() {
  const [list, err, reload] = useLoad(() => api.get<Competitor[]>("/competitors"));
  const [form, setForm] = useState<CompetitorIn>(blank);
  const [urls, setUrls] = useState("");
  const [feeds, setFeeds] = useState("");
  const [formErr, setFormErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);

  async function discover() {
    if (!form.domain.trim()) return;
    setDiscovering(true);
    setFormErr(null);
    setNotes([]);
    try {
      const d = await api.get<{
        domain: string; name: string | null; pricing_url: string | null; product_urls: string[]; feed_urls: string[];
        careers_provider: "greenhouse" | "lever" | null; careers_token: string | null; news_query: string | null; notes: string[];
      }>(`/discover?domain=${encodeURIComponent(form.domain)}`);
      setForm({ ...form, domain: d.domain, name: form.name || d.name || "", pricing_url: d.pricing_url ?? "",
                news_query: d.news_query ?? "", careers_provider: d.careers_provider, careers_token: d.careers_token ?? "" });
      setUrls(d.product_urls.join(" "));
      setFeeds(d.feed_urls.join(" "));
      setNotes(d.notes);
    } catch (e) {
      setFormErr(String((e as Error).message));
    } finally {
      setDiscovering(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setFormErr(null);
    try {
      await api.post("/competitors", {
        ...form,
        product_urls: urls.split(/\s+/).filter(Boolean),
        feed_urls: feeds.split(/\s+/).filter(Boolean),
        careers_provider: form.careers_provider || null,
        careers_token: form.careers_token || null,
        pricing_url: form.pricing_url || null,
      });
      setForm(blank);
      setUrls("");
      setFeeds("");
      setNotes([]);
      setOpen(false);
      reload();
    } catch (e) {
      setFormErr(String((e as Error).message));
    }
  }

  async function remove(c: Competitor) {
    if (!confirm(`Delete ${c.name} and all its data?`)) return;
    await api.del(`/competitors/${c.id}`);
    reload();
  }

  const set = (k: keyof CompetitorIn) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="space-y-5">
      <PageHeader
        index="04"
        title="Competitors"
        description="Tracked companies and every source Veyra watches for them."
        actions={<button className={open ? btnSecondaryCls : btnCls} aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "Cancel" : <><IconPlus />Add competitor</>}</button>}
      />
      {err && <ErrorBox error={err} />}
      {open && (
        <div className="anim-route">
          <Card title="New competitor">
            <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
              <div className="flex min-w-0 flex-col gap-1 md:col-span-2">
                <label htmlFor="comp-domain" className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-2">Domain <span aria-hidden="true" className="text-accent">*</span></label>
                <div className="flex gap-2">
                  <input id="comp-domain" required placeholder="any company, e.g. duolingo.com" className={inputCls} value={form.domain} onChange={set("domain")}
                    aria-describedby="comp-domain-hint"
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); discover(); } }} />
                  <button type="button" className={btnSecondaryCls} onClick={discover} disabled={discovering || !form.domain.trim()}>
                    <IconSearch />{discovering ? "Discovering…" : "Discover"}
                  </button>
                </div>
                <p id="comp-domain-hint" className="text-xs text-muted">Type a domain and press Discover: Veyra visits the site politely and fills in the fields below. Review them before saving.</p>
                {notes.length > 0 && (
                  <ul className="mt-1 space-y-0.5 rounded-[6px] border border-line bg-surface-2 p-2.5 font-mono text-xs text-ink-2" aria-live="polite">
                    {notes.map((n) => <li key={n} className="before:mr-1.5 before:text-muted before:content-['›']">{n}</li>)}
                  </ul>
                )}
              </div>
              <Field label="Name *"><input required className={inputCls} value={form.name} onChange={set("name")} /></Field>
              <Field label="Pricing URL"><input className={inputCls} value={form.pricing_url ?? ""} onChange={set("pricing_url")} /></Field>
              <Field label="News query"><input className={inputCls} value={form.news_query ?? ""} onChange={set("news_query")} /></Field>
              <Field label="Careers provider">
                <select className={inputCls} value={form.careers_provider ?? ""} onChange={set("careers_provider")}>
                  <option value="">none</option><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option>
                </select>
              </Field>
              <Field label="Careers board token"><input className={inputCls} value={form.careers_token ?? ""} onChange={set("careers_token")} /></Field>
              <Field label="Product / changelog URLs" wide hint="Space separated."><input className={inputCls} value={urls} onChange={(e) => setUrls(e.target.value)} /></Field>
              <Field label="Blog / changelog RSS or Atom feeds" wide hint="Space separated, optional.">
                <input className={inputCls} value={feeds} onChange={(e) => setFeeds(e.target.value)} placeholder="https://example.com/blog/feed.xml" />
              </Field>
              {formErr && <div className="md:col-span-2"><ErrorBox error={formErr} /></div>}
              <div className="flex gap-2 border-t border-line pt-4 md:col-span-2"><button className={btnCls} type="submit">Save</button></div>
            </form>
          </Card>
        </div>
      )}
      {list && list.length === 0 && <Empty>No competitors yet. Press <b>Add competitor</b>, type any company's domain and press <b>Discover</b>.</Empty>}
      {!list && !err && <div className="grid gap-3">{[0, 1].map((i) => <div key={i} className="rounded-[12px] border border-line bg-surface p-4"><Skeleton className="h-4 w-40" /><Skeleton className="mt-4 h-3 w-full" /><Skeleton className="mt-2 h-3 w-5/6" /></div>)}</div>}
      <div className="grid gap-4">
        {list?.map((c, i) => (
          <div key={c.id} className="anim-rise" style={{ "--i": i } as CSSProperties}>
            <Card
              title={<span className="flex items-center gap-2.5 normal-case tracking-normal">
                <span aria-hidden="true" className="flex h-7 w-7 items-center justify-center rounded-[6px] bg-ink font-mono text-sm font-semibold text-bg">{c.name.slice(0, 1).toUpperCase()}</span>
                <span className="font-sans text-base font-semibold text-ink">{c.name}</span>
              </span>}
              right={<button onClick={() => remove(c)} className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-[6px] px-2 font-mono text-xs font-medium hover:bg-[var(--bad-bg)]" style={{ color: "var(--bad)" }}>
                <IconTrash />Delete<span className="sr-only"> {c.name}</span>
              </button>}
              flush
            >
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line bg-surface-2 px-4 py-2 font-mono text-xs text-ink-2">
                <a className="inline-flex items-center gap-1 hover:text-accent hover:underline" href={`https://${c.domain}`} target="_blank" rel="noreferrer">{c.domain}<IconExternal /></a>
                {c.careers_provider && <span className="text-muted">jobs via {c.careers_provider}/{c.careers_token}</span>}
                <span className="tnum ml-auto text-muted">{c.sources.length} sources</span>
              </div>
              <ul className="divide-y divide-line">
                {c.sources.map((s) => (
                  <li key={s.id} className="grid min-w-0 grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 px-4 py-2 text-sm sm:grid-cols-[7.5rem_minmax(0,1fr)_auto]">
                    <span>{s.source_type === "early_signal" ? <ProvenanceTag kind="early" /> : <Badge tone={TONE[s.source_type]}>{s.source_type}</Badge>}</span>
                    <a href={s.url} target="_blank" rel="noreferrer" title={s.url} className="truncate font-mono text-xs text-ink-2 hover:text-accent hover:underline">{s.url}</a>
                    <span className="tnum col-start-2 font-mono text-[11px] text-muted sm:col-start-auto sm:text-right">{s.last_checked_at ? new Date(s.last_checked_at).toLocaleString() : "never checked"}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        ))}
      </div>
    </div>
  );
}
