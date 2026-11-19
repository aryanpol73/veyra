import { FormEvent, useState } from "react";
import { api, Competitor, CompetitorIn } from "../api/client";
import { Badge, Card, Empty, ErrorBox, btnCls, inputCls, useLoad } from "../components/ui";

const TONE = { page: "info", jobs: "ok", news: "muted", early_signal: "warn" } as const;

const blank: CompetitorIn = { name: "", domain: "", pricing_url: "", product_urls: [], careers_provider: null, careers_token: "", news_query: "" };

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
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Competitors</h1>
        <button className={btnCls} onClick={() => setOpen((o) => !o)}>{open ? "Cancel" : "Add competitor"}</button>
      </div>
      {err && <ErrorBox error={err} />}
      {open && (
        <Card title="New competitor">
          <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
            <div className="text-sm md:col-span-2">
              Domain
              <div className="flex gap-2">
                <input required placeholder="any company, e.g. duolingo.com" className={inputCls} value={form.domain} onChange={set("domain")}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); discover(); } }} />
                <button type="button" className={btnCls} onClick={discover} disabled={discovering || !form.domain.trim()}>
                  {discovering ? "Discovering…" : "Discover"}
                </button>
              </div>
              <p className="mt-1 text-xs text-zinc-500">Type a domain and press Discover: Veyra visits the site politely and fills in the fields below. Review them before saving.</p>
              {notes.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-zinc-600 dark:text-zinc-400">{notes.map((n) => <li key={n}>{n}</li>)}</ul>}
            </div>
            <label className="text-sm">Name<input required className={inputCls} value={form.name} onChange={set("name")} /></label>
            <label className="text-sm">Pricing URL<input className={inputCls} value={form.pricing_url ?? ""} onChange={set("pricing_url")} /></label>
            <label className="text-sm">News query<input className={inputCls} value={form.news_query ?? ""} onChange={set("news_query")} /></label>
            <label className="text-sm">Careers provider
              <select className={inputCls} value={form.careers_provider ?? ""} onChange={set("careers_provider")}>
                <option value="">none</option><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option>
              </select>
            </label>
            <label className="text-sm">Careers board token<input className={inputCls} value={form.careers_token ?? ""} onChange={set("careers_token")} /></label>
            <label className="text-sm md:col-span-2">Product / changelog URLs (space separated)<input className={inputCls} value={urls} onChange={(e) => setUrls(e.target.value)} /></label>
            <label className="text-sm md:col-span-2">Blog / changelog RSS or Atom feeds (space separated, optional)<input className={inputCls} value={feeds} onChange={(e) => setFeeds(e.target.value)} placeholder="https://example.com/blog/feed.xml" /></label>
            {formErr && <div className="md:col-span-2"><ErrorBox error={formErr} /></div>}
            <div className="md:col-span-2"><button className={btnCls} type="submit">Save</button></div>
          </form>
        </Card>
      )}
      {list && list.length === 0 && <Empty>No competitors yet. Run <code>python -m app.db.seed</code> or add one.</Empty>}
      <div className="grid gap-3">
        {list?.map((c) => (
          <Card key={c.id} title={c.name} right={<button onClick={() => remove(c)} className="text-xs text-red-600 hover:underline">Delete</button>}>
            <div className="mb-2 text-sm text-zinc-500">
              <a className="hover:underline" href={`https://${c.domain}`} target="_blank" rel="noreferrer">{c.domain}</a>
              {c.careers_provider && <> · jobs via {c.careers_provider}/{c.careers_token}</>}
            </div>
            <ul className="space-y-1 text-sm">
              {c.sources.map((s) => (
                <li key={s.id} className="flex min-w-0 items-center gap-2">
                  <Badge tone={TONE[s.source_type]}>{s.source_type === "early_signal" ? "Early Signal" : s.source_type}</Badge>
                  <a href={s.url} target="_blank" rel="noreferrer" className="truncate text-zinc-600 hover:underline dark:text-zinc-400">{s.url}</a>
                  <span className="ml-auto shrink-0 text-xs text-zinc-400">{s.last_checked_at ? new Date(s.last_checked_at).toLocaleString() : "never checked"}</span>
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}
