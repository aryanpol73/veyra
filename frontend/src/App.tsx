import { ComponentType, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import Overview from "./pages/Overview";
import Competitors from "./pages/Competitors";
import Feed from "./pages/Feed";
import Hypotheses from "./pages/Hypotheses";
import Evaluation from "./pages/Evaluation";
import Ask from "./pages/Ask";
import Reports from "./pages/Reports";
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

export default function App() {
  const [dark, toggle] = useTheme();
  const { pathname } = useLocation();

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
          <p className="font-mono text-[10.5px] leading-relaxed text-muted">Scores are heuristic until calibrated on the Evaluation page.</p>
        </div>
      </aside>

      {/* mobile top bar */}
      <header className="sticky top-0 z-30 border-b border-line bg-[color-mix(in_srgb,var(--bg-deep)_90%,transparent)] backdrop-blur-md md:hidden">
        <div className="flex items-center justify-between px-4 py-2.5">
          <Brand />
          <ThemeToggle dark={dark} toggle={toggle} compact />
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
        <div key={pathname} className="anim-route relative mx-auto w-full max-w-[1240px] px-4 pb-16 pt-6 md:px-8 md:pt-8">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/competitors" element={<Competitors />} />
            <Route path="/hypotheses" element={<Hypotheses />} />
            <Route path="/feed" element={<Feed />} />
            <Route path="/ask" element={<Ask />} />
            <Route path="/evaluation" element={<Evaluation />} />
            <Route path="/reports" element={<Reports />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
