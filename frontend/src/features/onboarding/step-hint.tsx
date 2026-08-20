"use client";

import type { ReactNode } from "react";
import { RobotAvatar } from "@/features/chat/components/robot-avatar";

/** Compact coach line from the clinic assistant — not a fake chat bubble.
 * Speech bubbles and typing dots belong in the widget, not the setup wizard. */
export function StepHint({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <RobotAvatar size="sm" className="mt-0.5 rounded-full bg-primary" />
      <p className="pt-1 text-sm leading-relaxed text-muted-foreground">{children}</p>
    </div>
  );
}
