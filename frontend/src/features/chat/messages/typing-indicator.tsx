"use client";

import { RobotAvatar } from "@/features/chat/components/robot-avatar";

export function TypingIndicator() {
  return (
    <div className="flex gap-2">
      <RobotAvatar size="sm" className="mt-1" animate />
      <div className="flex items-center gap-1 rounded-[12px] rounded-bl-[4px] border border-border bg-white px-3.5 py-3 shadow-sm">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-pulse rounded-full bg-primary/60"
            style={{ animationDelay: `${i * 150}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
