import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type InsightTone = "paper" | "ink" | "wash";

export function InsightCard({
  tone = "paper",
  className,
  children,
  overflow = "hidden",
}: {
  tone?: InsightTone;
  className?: string;
  children?: ReactNode;
  overflow?: "hidden" | "visible";
}) {
  return (
    <div
      data-insight-tone={tone}
      className={cn(
        "insight-card relative flex flex-col text-sm",
        overflow === "visible" ? "overflow-visible" : "overflow-hidden",
        tone === "paper" &&
          "bg-card text-card-foreground ring-1 ring-foreground/[0.06]",
        tone === "ink" &&
          "bg-[var(--insight-ink)] text-white ring-1 ring-white/10",
        tone === "wash" &&
          "bg-[var(--insight-wash)] text-[var(--insight-ink-deep)] ring-1 ring-[var(--insight-lilac)]/40",
        className
      )}
    >
      {children}
    </div>
  );
}
