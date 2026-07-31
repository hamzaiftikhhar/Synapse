"use client";

import { useEffect, useState } from "react";
import { RobotAvatar } from "@/features/chat/components/robot-avatar";
import { BotMetaRow } from "@/features/chat/components/chat-chrome";
import {
  prefersReducedMotion,
} from "@/features/chat/natural-pace";
import {
  statusPhraseAt,
  statusSequenceForMessage,
} from "@/features/chat/status-phrases";
import { cn } from "@/lib/utils";

export function TypingIndicator({
  assistantName,
  userHint = "",
}: {
  assistantName?: string;
  /** Last user message — biases calm status copy (booking vs clinic facts). */
  userHint?: string;
}) {
  const [showSkeleton, setShowSkeleton] = useState(false);
  const [phrase, setPhrase] = useState(() =>
    statusPhraseAt(statusSequenceForMessage(userHint), 0)
  );
  const [fadeKey, setFadeKey] = useState(0);

  useEffect(() => {
    const t = window.setTimeout(() => setShowSkeleton(true), 500);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    const sequence = statusSequenceForMessage(userHint);
    const started = performance.now();
    setPhrase(statusPhraseAt(sequence, 0));
    setFadeKey((k) => k + 1);

    if (prefersReducedMotion()) return;

    let last = sequence[0] ?? "Thinking";
    const id = window.setInterval(() => {
      const next = statusPhraseAt(sequence, performance.now() - started);
      if (next === last) return;
      last = next;
      setPhrase(next);
      setFadeKey((k) => k + 1);
    }, 400);

    return () => window.clearInterval(id);
  }, [userHint]);

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
          <p
            key={fadeKey}
            className={cn(
              "synapse-thinking-dots text-sm text-muted-foreground",
              "motion-safe:animate-[synapse-status-in_220ms_ease-out]"
            )}
          >
            {phrase}
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
