import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

/** Briefs and chat answers include text scraped from third-party pages, so HTML is always sanitised. */
export default function Markdown({ text }: { text: string }) {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(text, { async: false, gfm: true }) as string), [text]);
  return (
    <div
      className="prose-veyra text-sm leading-relaxed [&_a]:text-sky-700 [&_a:hover]:underline dark:[&_a]:text-sky-400 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mb-1 [&_h2]:mt-5 [&_h2]:text-base [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_p]:my-2 [&_strong]:font-semibold [&_em]:text-zinc-600 dark:[&_em]:text-zinc-400"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
