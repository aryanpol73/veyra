import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

/** Briefs and chat answers include text scraped from third-party pages, so HTML is always sanitised. */
export default function Markdown({ text, size = "sm" }: { text: string; size?: "sm" | "md" }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false, gfm: true }) as string), [text]);
  return (
    <div
      className={`prose-veyra max-w-none text-ink-2 [overflow-wrap:anywhere] ${size === "md" ? "text-[15px] leading-7" : "text-sm leading-relaxed"}
        [&_a]:font-medium [&_a]:text-accent [&_a]:underline [&_a]:decoration-[color-mix(in_srgb,var(--accent)_40%,transparent)] [&_a]:underline-offset-2 [&_a:hover]:decoration-accent
        [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h1]:tracking-tight [&_h1]:text-ink
        [&_h2]:mb-2 [&_h2]:mt-7 [&_h2]:border-b [&_h2]:border-line [&_h2]:pb-1.5 [&_h2]:font-mono [&_h2]:text-xs [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.12em] [&_h2]:text-ink
        [&_h3]:mb-1 [&_h3]:mt-5 [&_h3]:font-semibold [&_h3]:text-ink
        [&_ul]:my-2 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-1 [&_ul>li]:ml-5 [&_ul>li]:list-disc [&_li::marker]:text-muted
        [&_p]:my-2.5 [&_strong]:font-semibold [&_strong]:text-ink [&_em]:text-muted
        [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-accent [&_blockquote]:bg-surface-2 [&_blockquote]:px-3 [&_blockquote]:py-1.5
        [&_code]:rounded-[2px] [&_code]:bg-sunken [&_code]:px-1 [&_code]:font-mono [&_code]:text-[0.9em]
        [&_hr]:my-6 [&_hr]:border-line
        [&_table]:my-3 [&_table]:block [&_table]:overflow-x-auto [&_table]:text-sm [&_th]:border-b [&_th]:border-line [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-mono [&_th]:text-xs [&_th]:text-muted [&_td]:border-b [&_td]:border-line [&_td]:px-2 [&_td]:py-1`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
