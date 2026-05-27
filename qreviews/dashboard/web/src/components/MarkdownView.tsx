import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownView({ source }: { source: string | null | undefined }) {
  if (!source) {
    return (
      <div className="pt-mono text-[12px] text-[var(--pt-muted)] italic">
        No comment posted for this revision.
      </div>
    );
  }
  return (
    <div className="pt-md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{source}</ReactMarkdown>
    </div>
  );
}
