import { cn } from "@/lib/utils";
import type { KnowledgeDocument } from "@/types/api";
import { statusLabel, statusTone } from "./utils";

const toneClass: Record<
  ReturnType<typeof statusTone>,
  string
> = {
  queued:
    "bg-amber-50 text-amber-800 ring-amber-200/80 dark:bg-amber-950/40 dark:text-amber-200 dark:ring-amber-800/60",
  processing:
    "bg-sky-50 text-sky-800 ring-sky-200/80 dark:bg-sky-950/40 dark:text-sky-200 dark:ring-sky-800/60",
  completed:
    "bg-emerald-50 text-emerald-800 ring-emerald-200/80 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-800/60",
  failed:
    "bg-red-50 text-red-800 ring-red-200/80 dark:bg-red-950/40 dark:text-red-200 dark:ring-red-800/60",
  cancelled:
    "bg-zinc-100 text-zinc-600 ring-zinc-200/80 dark:bg-zinc-800/50 dark:text-zinc-300 dark:ring-zinc-700/60",
};

export function DocumentStatusBadge({
  document,
  className,
}: {
  document: KnowledgeDocument;
  className?: string;
}) {
  const tone = statusTone(document.status);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[4px] px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset",
        toneClass[tone],
        className
      )}
    >
      {statusLabel(document)}
    </span>
  );
}
