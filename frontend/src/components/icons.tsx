import { SVGProps } from "react";

/** Small inline stroke icon set (1.5px, 24 grid). Decorative by default: pair with visible text. */
type P = SVGProps<SVGSVGElement> & { size?: number };
const base = ({ size = 16, ...p }: P) => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
  "aria-hidden": true, focusable: false, ...p,
});

export const IconOverview = (p: P) => (<svg {...base(p)}><rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" /><rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" /></svg>);
export const IconHypothesis = (p: P) => (<svg {...base(p)}><circle cx="12" cy="12" r="8.5" /><path d="M12 3.5V12l6 6" /><path d="M12 7.5v0" /></svg>);
export const IconFeed = (p: P) => (<svg {...base(p)}><path d="M4 11a9 9 0 0 1 9 9" /><path d="M4 4a16 16 0 0 1 16 16" /><circle cx="5" cy="19" r="1.2" fill="currentColor" /></svg>);
export const IconCompetitors = (p: P) => (<svg {...base(p)}><path d="M3 21V9l6-4 6 4v12" /><path d="M15 21V13l6-3v11" /><path d="M7 13h4M7 17h4" /></svg>);
export const IconAsk = (p: P) => (<svg {...base(p)}><path d="M4 5h16v11H9l-5 4z" /><path d="M9 10h6" /></svg>);
export const IconEval = (p: P) => (<svg {...base(p)}><path d="M4 20 20 4" strokeDasharray="2 3" /><circle cx="8" cy="15" r="1.6" /><circle cx="13" cy="10" r="1.6" /><circle cx="17" cy="8" r="1.6" /><path d="M4 4v16h16" /></svg>);
export const IconReports = (p: P) => (<svg {...base(p)}><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4" /><path d="M9 12h7M9 16h5" /></svg>);
export const IconSun = (p: P) => (<svg {...base(p)}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>);
export const IconMoon = (p: P) => (<svg {...base(p)}><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" /></svg>);
export const IconExternal = (p: P) => (<svg {...base({ size: 12, ...p })}><path d="M14 4h6v6" /><path d="M20 4 11 13" /><path d="M18 14v6H4V6h6" /></svg>);
export const IconArrowRight = (p: P) => (<svg {...base({ size: 14, ...p })}><path d="M5 12h14M13 6l6 6-6 6" /></svg>);
export const IconRefresh = (p: P) => (<svg {...base({ size: 14, ...p })}><path d="M20 11a8 8 0 0 0-14.6-4.5L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16" /><path d="M20 20v-4h-4" /></svg>);
export const IconPlay = (p: P) => (<svg {...base({ size: 14, ...p })}><path d="M7 5v14l11-7z" /></svg>);
export const IconChevron = (p: P) => (<svg {...base({ size: 14, ...p })}><path d="m9 6 6 6-6 6" /></svg>);
export const IconAlert = (p: P) => (<svg {...base(p)}><path d="M12 3 2 20h20z" /><path d="M12 10v4M12 17v.5" /></svg>);
export const IconSend = (p: P) => (<svg {...base(p)}><path d="M4 12 20 4l-6 16-3-7z" /></svg>);
export const IconPlus = (p: P) => (<svg {...base({ size: 14, ...p })}><path d="M12 5v14M5 12h14" /></svg>);
export const IconTrash = (p: P) => (<svg {...base({ size: 14, ...p })}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>);
export const IconSearch = (p: P) => (<svg {...base({ size: 14, ...p })}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></svg>);
export const IconTool = (p: P) => (<svg {...base({ size: 14, ...p })}><path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3z" /><path d="M14.5 6.5 17 4l3 3-2.5 2.5" /></svg>);

/** Veyra mark: a gauge arc with a needle — the confidence motif in miniature. */
export function VeyraMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="0.75" y="0.75" width="22.5" height="22.5" rx="3" fill="var(--ink)" />
      <path d="M5.5 15.5a6.5 6.5 0 0 1 13 0" fill="none" stroke="var(--bg)" strokeWidth="1.6" strokeLinecap="round" strokeDasharray="1.2 2.2" />
      <path d="M12 15.5 16 9.5" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="12" cy="15.5" r="1.6" fill="var(--accent)" />
    </svg>
  );
}
