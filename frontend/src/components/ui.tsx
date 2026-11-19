import { CSSProperties, ReactNode, useEffect, useState } from "react";
import { IconAlert, IconExternal, VeyraMark } from "./icons";

/* ───────────────────────────── layout primitives ───────────────────────────── */

export function PageHeader({ index, title, description, actions }: { index: string; title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-line pb-5">
      <div className="min-w-0">
        <div className="font-mono text-[11px] font-medium uppercase tracking-[0.16em] text-accent">
          <span className="tnum">{index}</span> <span aria-hidden="true">/</span> {title}
        </div>
        <h1 className="mt-1.5 text-[26px] font-semibold leading-tight tracking-[-0.02em] text-ink md:text-[30px]">{title}</h1>
        {description && <div className="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted">{description}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, children, right, flush, className = "", id }: {
  title?: ReactNode; children: ReactNode; right?: ReactNode; flush?: boolean; className?: string; id?: string;
}) {
  return (
    <section id={id} className={`min-w-0 rounded-[4px] border border-line bg-surface ${className}`}>
      {(title || right) && (
        <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line px-4 py-2">
          {title && <h2 className="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-ink-2">{title}</h2>}
          {right}
        </div>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

/** Small uppercase label used for sub-sections inside a card. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <h3 className={`font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-muted ${className}`}>{children}</h3>;
}

/* ───────────────────────────── tags & badges ───────────────────────────── */

const TONE_VARS = {
  ok: "ok", warn: "warn", bad: "bad", info: "info", muted: "neutral", synthetic: "synth",
} as const;
export type Tone = keyof typeof TONE_VARS;

export function toneStyle(tone: Tone): CSSProperties {
  const v = TONE_VARS[tone];
  return { color: `var(--${v})`, background: `var(--${v}-bg)`, borderColor: `var(--${v}-line)` };
}

export function Badge({ tone = "muted", children, title, className = "" }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  const provenance = tone === "synthetic";
  return (
    <span
      title={title}
      style={toneStyle(tone)}
      className={`inline-flex max-w-full items-center gap-1 rounded-[3px] border px-1.5 py-px font-mono text-[11px] font-medium leading-4 [overflow-wrap:anywhere] ${provenance ? "border-dashed" : ""} ${className}`}
    >
      {children}
    </span>
  );
}

/** Replay / Synthetic / Early Signal — non-live provenance gets a dashed, hatched treatment so it can't be mistaken for live data. */
export function ProvenanceTag({ kind }: { kind: "replay" | "synthetic" | "early" }) {
  const label = kind === "replay" ? "Replay" : kind === "synthetic" ? "Synthetic" : "Early Signal";
  const v = kind === "early" ? "warn" : "synth";
  return (
    <span
      className="hatch-soft inline-flex items-center gap-1 rounded-[3px] border border-dashed px-1.5 py-px font-mono text-[11px] font-semibold uppercase leading-4 tracking-[0.06em]"
      style={{ color: `var(--${v})`, borderColor: `var(--${v}-line)`, backgroundColor: `var(--${v}-bg)` }}
    >
      <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true"><path d={kind === "early" ? "M4 0 8 8H0z" : "M0 4h8M4 0v8"} fill={kind === "early" ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" /></svg>
      {label}
    </span>
  );
}

/* status: pie glyph fill = the band's lower threshold (0 / .40 / .70 / 1), plus text. */
const STATUS_META: Record<string, { tone: Tone; fill: number }> = {
  emerging: { tone: "muted", fill: 0 }, plausible: { tone: "info", fill: 0.4 }, likely: { tone: "warn", fill: 0.7 },
  confirmed: { tone: "ok", fill: 1 }, refuted: { tone: "bad", fill: -1 }, stale: { tone: "muted", fill: -2 },
};

function Pie({ fill }: { fill: number }) {
  const r = 4.5, c = 6;
  if (fill === -1) return <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx={c} cy={c} r={r} fill="none" stroke="currentColor" strokeWidth="1.4" /><path d="M3 9 9 3" stroke="currentColor" strokeWidth="1.4" /></svg>;
  if (fill === -2) return <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx={c} cy={c} r={r} fill="none" stroke="currentColor" strokeWidth="1.4" strokeDasharray="1.6 1.8" /></svg>;
  const a = fill * 2 * Math.PI;
  const x = c + r * Math.sin(a), y = c - r * Math.cos(a);
  const d = fill >= 1 ? "" : `M${c} ${c} L${c} ${c - r} A${r} ${r} 0 ${fill > 0.5 ? 1 : 0} 1 ${x.toFixed(2)} ${y.toFixed(2)} Z`;
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <circle cx={c} cy={c} r={r} fill={fill >= 1 ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.4" />
      {fill > 0 && fill < 1 && <path d={d} fill="currentColor" />}
    </svg>
  );
}

export function StatusTag({ status }: { status: string }) {
  const m = STATUS_META[status] ?? { tone: "muted" as Tone, fill: 0 };
  return (
    <span style={toneStyle(m.tone)} className="inline-flex items-center gap-1 rounded-[3px] border px-1.5 py-px font-mono text-[11px] font-semibold uppercase leading-4 tracking-[0.06em]">
      <Pie fill={m.fill} />{status}
    </span>
  );
}

const PRIORITY_META: Record<string, { tone: Tone; bars: number }> = {
  critical: { tone: "bad", bars: 4 }, high: { tone: "warn", bars: 3 }, medium: { tone: "info", bars: 2 }, low: { tone: "muted", bars: 1 },
};

/** Priority = text + signal-strength bars, so it reads without colour. */
export function PriorityTag({ priority }: { priority: string }) {
  const m = PRIORITY_META[priority] ?? { tone: "muted" as Tone, bars: 1 };
  return (
    <span style={toneStyle(m.tone)} className="inline-flex items-center gap-1 rounded-[3px] border px-1.5 py-px font-mono text-[11px] font-semibold uppercase leading-4 tracking-[0.06em]">
      <svg width="11" height="10" viewBox="0 0 11 10" aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <rect key={i} x={i * 3} y={7 - i * 2} width="2" height={3 + i * 2} fill="currentColor" opacity={i < m.bars ? 1 : 0.25} />
        ))}
      </svg>
      {priority}
    </span>
  );
}

/* ───────────────────────────── confidence gauge (signature motif) ─────────────────────────────
   Track marked at the real status thresholds; hatched fill = heuristic, not a calibrated probability. */
const THRESHOLDS = [0.4, 0.7, 0.9];

export function ConfidenceGauge({ value, size = "sm", label }: { value: number; size?: "sm" | "lg"; label?: string }) {
  const v = Math.max(0, Math.min(1, value));
  const lg = size === "lg";
  return (
    <div className="w-full" role="img" aria-label={label ?? `confidence ${v.toFixed(2)} on a 0 to 1 scale (uncalibrated heuristic)`}>
      <div className={`relative ${lg ? "h-3" : "h-1.5"} w-full overflow-visible`}>
        <div className="absolute inset-0 overflow-hidden rounded-[1px] border border-line bg-sunken">
          <div className="anim-fill hatch absolute inset-y-0 left-0" style={{ width: `${v * 100}%` }} />
        </div>
        {THRESHOLDS.map((t) => (
          <span key={t} className={`absolute w-px bg-line-strong ${lg ? "-top-1 -bottom-1" : "-top-0.5 -bottom-0.5"}`} style={{ left: `${t * 100}%` }} aria-hidden="true" />
        ))}
        <span
          aria-hidden="true"
          className={`absolute w-0.5 -translate-x-1/2 rounded-full bg-ink ${lg ? "-top-1.5 -bottom-1.5" : "-top-1 -bottom-1"}`}
          style={{ left: `${v * 100}%` }}
        />
      </div>
      {lg && (
        <div className="relative mt-2 h-4 font-mono text-[11px] text-muted" aria-hidden="true">
          <span className="absolute left-0">0</span>
          {THRESHOLDS.map((t) => (
            <span key={t} className="tnum absolute -translate-x-1/2" style={{ left: `${t * 100}%` }}>{t.toFixed(2).slice(1)}</span>
          ))}
          <span className="absolute right-0">1</span>
        </div>
      )}
    </div>
  );
}

/* ───────────────────────────── evidence ledger marks ───────────────────────────── */

export function StanceMark({ stance }: { stance: "supports" | "contradicts" | "neutral" | string }) {
  const s = stance === "supports" ? { g: "+", v: "ok", solid: true } : stance === "contradicts" ? { g: "−", v: "bad", solid: false } : { g: "·", v: "neutral", solid: false };
  return (
    <span
      aria-label={stance}
      title={stance}
      className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-[3px] border font-mono text-[13px] font-semibold leading-none ${s.v === "neutral" ? "border-dashed" : ""}`}
      style={s.solid ? { background: `var(--${s.v})`, borderColor: `var(--${s.v})`, color: "var(--surface)" } : { color: `var(--${s.v})`, borderColor: `var(--${s.v}-line)`, background: `var(--${s.v}-bg)` }}
    >
      {s.g}
    </span>
  );
}

/** Diverging micro-bar for a logit contribution: direction + sign + number, not colour alone. */
export function ContributionBar({ value, max = 1.5 }: { value: number; max?: number }) {
  const w = Math.min(1, Math.abs(value) / max) * 50;
  const pos = value >= 0;
  return (
    <span className="inline-flex items-center gap-2" title="logit contribution after decay, reliability, independence and caps">
      <span className="relative inline-block h-2 w-16 shrink-0 bg-sunken" aria-hidden="true">
        <span className="absolute inset-y-[-2px] left-1/2 w-px bg-line-strong" />
        <span className="absolute inset-y-0" style={{ [pos ? "left" : "right"]: "50%", width: `${w}%`, background: `var(--${pos ? "ok" : "bad"})` }} />
      </span>
      <span className="tnum font-mono text-xs font-medium text-ink-2">{pos ? "+" : ""}{value.toFixed(2)}</span>
    </span>
  );
}

export function ExtLink({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
      className={`inline-flex items-center gap-1 font-mono text-xs font-medium text-accent underline-offset-2 hover:underline ${className}`}>
      {children}<IconExternal /><span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

/* ───────────────────────────── numbers & states ───────────────────────────── */

export function Stat({ label, value, sub, index }: { label: string; value: ReactNode; sub?: ReactNode; index?: number }) {
  return (
    <div className="anim-rise relative min-w-0 rounded-[4px] border border-line bg-surface p-4" style={{ "--i": index ?? 0 } as CSSProperties}>
      <div className="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-muted">{label}</div>
      <div className="tnum mt-2 text-[28px] font-semibold leading-none tracking-[-0.02em] text-ink">{value}</div>
      {sub && <div className="tnum mt-2 font-mono text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="hatch-soft flex flex-col items-center gap-3 rounded-[4px] border border-dashed border-line-strong px-6 py-10 text-center text-sm text-muted">
      <span className="opacity-70"><VeyraMark size={20} /></span>
      <div className="max-w-md leading-relaxed">{children}</div>
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div role="alert" style={toneStyle("bad")} className="flex items-start gap-2 rounded-[4px] border p-3 text-sm [overflow-wrap:anywhere]">
      <IconAlert className="mt-0.5 shrink-0" />
      <span>{error}</span>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`relative overflow-hidden rounded-[2px] bg-sunken ${className}`} aria-hidden="true">
    <div className="anim-scan absolute inset-y-0 w-1/4 bg-gradient-to-r from-transparent via-[color-mix(in_srgb,var(--line-strong)_45%,transparent)] to-transparent" />
  </div>;
}

/** Load data once; returns [data, error, reload]. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): [T | null, string | null, () => void] {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    fn().then((d) => live && (setData(d), setErr(null))).catch((e) => live && setErr(String(e.message ?? e)));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return [data, err, () => setTick((t) => t + 1)];
}

/* ───────────────────────────── controls ───────────────────────────── */

export const inputCls =
  "h-10 w-full min-w-0 rounded-[3px] border border-line-strong bg-surface px-2.5 text-base text-ink placeholder:text-muted transition-colors hover:border-muted focus:border-accent sm:h-9 sm:text-sm";
export const btnCls =
  "inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-[3px] bg-accent px-3.5 text-sm font-medium text-on-accent transition-[background-color,transform] duration-150 hover:bg-accent-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 sm:h-9";
export const btnSecondaryCls =
  "inline-flex h-10 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-[3px] border border-line-strong bg-surface px-3 text-sm font-medium text-ink transition-[background-color,border-color,transform] duration-150 hover:border-muted hover:bg-surface-2 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 sm:h-9";
export const btnSmCls =
  "inline-flex h-8 cursor-pointer items-center justify-center gap-1 whitespace-nowrap rounded-[3px] border border-line-strong bg-surface px-2.5 font-mono text-xs font-medium text-ink-2 transition-colors hover:border-muted hover:bg-surface-2 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50";
export const linkCls = "text-ink underline decoration-line-strong underline-offset-[3px] transition-colors hover:decoration-accent";
