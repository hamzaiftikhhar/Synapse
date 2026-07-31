"use client";

import { useEffect, useState } from "react";
import { RobotAvatar } from "@/features/chat/components/robot-avatar";
import { BotMetaRow } from "@/features/chat/components/chat-chrome";

export function TypingIndicator({ assistantName }: { assistantName?: string }) {
  const [showSkeleton, setShowSkeleton] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setShowSkeleton(true), 500);
    return () => window.clearTimeout(t);
  }, []);

  return (
    <div className="synapse-chat-msg flex gap-2.5">
      <RobotAvatar
        size="sm"
        className="mt-5 shrink-0 rounded-full bg-primary"
        animate
      />
      <div className="min-w-0 max-w-[85%]">
        <BotMetaRow name={assistantName} />
        <div className="rounded-[18px] rounded-bl-md border border-border/80 bg-white px-3.5 py-3 shadow-[0_1px_3px_rgb(11_14_46/0.06)]">
          <p className="synapse-thinking-dots text-sm text-muted-foreground">
            Thinking
          </p>
          {showSkeleton ? (
            <div className="mt-3 space-y-2" aria-hidden>
              <div className="synapse-chat-skeleton h-2.5 w-[88%] rounded-full" />
              <div className="synapse-chat-skeleton h-2.5 w-[64%] rounded-full" />
              <div className="synapse-chat-skeleton h-2.5 w-[76%] rounded-full" />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
