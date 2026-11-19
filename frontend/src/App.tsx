import { ComponentType, Suspense, lazy, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import Overview from "./pages/Overview";
// Other pages load on demand: charts (recharts) and Markdown (marked + DOMPurify) stay out of the first load.
const Competitors = lazy(() => import("./pages/Competitors"));
const Feed = lazy(() => import("./pages/Feed"));
const Hypotheses = lazy(() => import("./pages/Hypotheses"));
const Evaluation = lazy(() => import("./pages/Evaluation"));
const Ask = lazy(() => import("./pages/Ask"));
const Reports = lazy(() => import("./pages/Reports"));
import Login from "./pages/Login";
import { api, AuthStatus, UNAUTHORIZED } from "./api/client";
import {
  IconAsk, IconCompetitors, IconEval, IconFeed, IconHypothesis, IconMoon, IconOverview, IconReports, IconSun, VeyraMark,
} from "./components/icons";

const NAV: { to: string; label: string; short: string; icon: ComponentType<{ size?: number }> }[] = [
  { to: "/", label: "Overview", short: "Overview", icon: IconOverview },
  { to: "/hypotheses", label: "Hypotheses", short: "Hypotheses", icon: IconHypothesis },
  { to: "/feed", label: "Intelligence Feed", short: "Feed", icon: IconFeed },
  { to: "/competitors", label: "Competitors", short: "Competitors", icon: IconCompetitors },
  { to: "/ask", label: "Ask Veyra", short: "Ask", icon: IconAsk },
  { to: "/evaluation", label: "Evaluation", short: "Evaluation", icon: IconEval },
  { to: "/reports", label: "Reports", short: "Reports", icon: IconReports },
];

function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState(() => {
    try {
      const saved = localStorage.getItem("veyra-theme");
      if (saved) return saved === "dark";
    } catch {}
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("veyra-theme", dark ? "dark" : "light");
    } catch {}
  }, [dark]);
  return [dark, () => setDark((d) => !d)];
}

function ThemeToggle({ dark, toggle, compact }: { dark: boolean; toggle: () => void; compact?: boolean }) {
  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${dark ? "light" : "dark"} theme`}
      className={`inline-flex cursor-pointer items-center gap-2 rounded-[6px] border border-line bg-surface text-ink-2 transition-colors hover:border-line-strong hover:text-ink ${compact ? "h-10 w-10 justify-center" : "h-9 w-full px-3 font-mono text-xs"}`}
    >
      {dark ? <IconSun size={15} /> : <IconMoon size={15} />}
      {!compact && <span>{dark ? "Light theme" : "Dark theme"}</span>}
    </button>
  );
}

function NotFound() {
  return (
    <div className="py-20 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.14em] text-muted">404</p>
      <h1 className="mt-2 font-display text-2xl font-bold text-ink">No such page</h1>
      <NavLink to="/" className="mt-4 inline-block text-sm text-accent underline underline-offset-4">Back to Overview</NavLink>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <VeyraMark size={32} />
      <div className="leading-none">
        <div className="font-display text-[18px] font-bold tracking-[0.16em] text-ink">VEYRA</div>
        <div className="mt-1 font-mono text-[10.5px] tracking-[0.04em] text-muted">hypothesis-driven CI</div>
      </div>
    </div>
  );
}

function useAuth(): [AuthStatus | null, () => void, () => void] {
  const [st, setSt] = useState<AuthStatus | null>(null);
  const refresh = () => {
    api.get<AuthStatus>("/auth/status").then(setSt).catch(() => setSt({ enabled: false, authenticated: true }));
  };
  useEffect(() => {
    refresh();
    const onUnauth = () => setSt((s) => (s ? { ...s, authenticated: false } : s));
    window.addEventListener(UNAUTHORIZED, onUnauth);
    return () => window.removeEventListener(UNAUTHORIZED, onUnauth);
  }, []);
  const logout = () => { api.post("/auth/logout").finally(refresh); };
  return [st, refresh, logout];
}

function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);
  return online;
}

export default function App() {
  const [dark, toggle] = useTheme();
  const { pathname } = useLocation();
  const [auth, refreshAuth, logout] = useAuth();
  const online = useOnline();

  if (auth === null) return <div className="min-h-dvh" aria-busy="true" />;
  if (auth.enabled && !auth.authenticated) return <Login onDone={refreshAuth} />;

  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <a href="#main" className="sr-only z-50 rounded-[6px] bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>

      {/* desktop rail */}
      <aside className="sticky top-0 z-20 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-[color-mix(in_srgb,var(--bg-deep)_82%,transparent)] backdrop-blur-md md:flex">
        <div className="border-b border-line px-5 py-5"><Brand /></div>
        <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3 py-4">
          <ul className="space-y-0.5">
            {NAV.map((n, i) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  end={n.to === "/"}
                  className={({ isActive }) =>
                    `group relative flex h-10 items-center gap-3 rounded-[6px] px-3 text-sm transition-colors ${
                      isActive ? "bg-[color-mix(in_srgb,var(--accent)_13%,transparent)] font-semibold text-ink" : "text-ink-2 hover:bg-[color-mix(in_srgb,var(--accent)_6%,transparent)] hover:text-ink"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span aria-hidden="true" className={`absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent transition-transform duration-200 ${isActive ? "scale-y-100" : "scale-y-0"}`} />
                      <span className={isActive ? "text-accent" : "text-muted group-hover:text-ink-2"}><n.icon size={16} /></span>
                      <span className="flex-1">{n.label}</span>
                      <span className="tnum font-mono text-[10.5px] text-muted" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="space-y-3 border-t border-line p-4">
          <ThemeToggle dark={dark} toggle={toggle} />
          {auth.enabled && (
            <button onClick={logout} className="inline-flex h-9 w-full cursor-pointer items-center rounded-[6px] border border-line bg-surface px-3 font-mono text-xs text-ink-2 transition-colors hover:border-line-strong hover:text-ink">
              Sign out
            </button>
          )}
          <p className="font-mono text-[10.5px] leading-relaxed text-muted">Scores are heuristic until calibrated on the Evaluation page.</p>
        </div>
      </aside>

      {/* mobile top bar */}
      <header className="sticky top-0 z-30 border-b border-line bg-[color-mix(in_srgb,var(--bg-deep)_90%,transparent)] backdrop-blur-md md:hidden">
        <div className="flex items-center justify-between px-4 py-2.5">
          <Brand />
          <div className="flex items-center gap-2">
            {auth.enabled && <button onClick={logout} className="h-10 cursor-pointer rounded-[6px] border border-line bg-surface px-3 font-mono text-xs text-ink-2 hover:text-ink">Sign out</button>}
            <ThemeToggle dark={dark} toggle={toggle} compact />
          </div>
        </div>
        <nav aria-label="Primary" className="scroll-thin -mb-px overflow-x-auto">
          <ul className="flex gap-1 px-2">
            {NAV.map((n) => (
              <li key={n.to} className="shrink-0">
                <NavLink
                  to={n.to}
                  end={n.to === "/"}
                  className={({ isActive }) =>
                    `flex h-11 items-center gap-1.5 border-b-2 px-2.5 text-sm transition-colors ${
                      isActive ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"
                    }`
                  }
                >
                  <n.icon size={15} />{n.short}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <main id="main" tabIndex={-1} className="relative min-w-0 flex-1 outline-none">
        <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
          <div className="radar-rings absolute -right-44 -top-56 h-[560px] w-[560px]">
            <div className="radar-sweep anim-sweep absolute inset-0" />
          </div>
          <div className="scanline anim-scanline absolute inset-x-0 top-0 h-40" />
        </div>
        {!online && (
          <div role="status" className="relative z-10 border-b border-line bg-surface px-4 py-2 text-center font-mono text-xs text-ink-2">
            You're offline. Veyra shows the app, but data needs a connection to the server.
          </div>
        )}
        <div key={pathname} className="anim-route relative mx-auto w-full max-w-[1240px] px-4 pb-16 pt-6 md:px-8 md:pt-8">
          <Suspense fallback={<div className="py-16 text-center font-mono text-xs text-muted" aria-busy="true">Loading…</div>}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/competitors" element={<Competitors />} />
            <Route path="/hypotheses" element={<Hypotheses />} />
            <Route path="/feed" element={<Feed />} />
            <Route path="/ask" element={<Ask />} />
            <Route path="/evaluation" element={<Evaluation />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
