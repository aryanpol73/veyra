import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import Competitors from "./pages/Competitors";
import Placeholder from "./pages/Placeholder";
import Feed from "./pages/Feed";
import Hypotheses from "./pages/Hypotheses";

const NAV = [
  { to: "/", label: "Overview" },
  { to: "/hypotheses", label: "Hypotheses" },
  { to: "/feed", label: "Intelligence Feed" },
  { to: "/competitors", label: "Competitors" },
  { to: "/ask", label: "Ask Veyra" },
  { to: "/evaluation", label: "Evaluation" },
  { to: "/reports", label: "Reports" },
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

export default function App() {
  const [dark, toggle] = useTheme();
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b border-zinc-200 bg-white md:w-56 md:border-b-0 md:border-r dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center justify-between p-4">
          <div>
            <div className="text-lg font-bold tracking-tight">VEYRA</div>
            <div className="text-xs text-zinc-500">hypothesis-driven CI</div>
          </div>
          <button onClick={toggle} className="rounded border border-zinc-300 px-2 py-1 text-xs dark:border-zinc-700" aria-label="Toggle theme">
            {dark ? "Light" : "Dark"}
          </button>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `whitespace-nowrap rounded px-3 py-1.5 text-sm ${
                  isActive ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-6">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/competitors" element={<Competitors />} />
          <Route path="/hypotheses" element={<Hypotheses />} />
          <Route path="/feed" element={<Feed />} />
          <Route path="/ask" element={<Placeholder title="Ask Veyra" phase={4} what="Chat grounded in the database via tool calls, with cited sources." />} />
          <Route path="/evaluation" element={<Placeholder title="Evaluation" phase={3} what="Leakage-safe replay backtest: precision, recall, lead time, Brier score, calibration with Wilson intervals." />} />
          <Route path="/reports" element={<Placeholder title="Reports" phase={4} what="Daily brief archive: what happened, why it matters, what to do." />} />
        </Routes>
      </main>
    </div>
  );
}
