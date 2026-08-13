import type { ReactNode } from "react";

export function StepHint({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-2xl border border-border bg-card px-4 py-3 text-sm leading-relaxed text-muted-foreground">
      {children}
    </p>
  );
}
