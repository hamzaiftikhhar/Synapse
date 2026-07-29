"use client";

import type { ChatActionHandler, ChatMessage } from "@/types/chat";

export function SuggestedQuestions({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const questions = (message.payload?.questions as string[]) || [];
  return (
    <div className="space-y-2">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        Suggested
      </p>
      <div className="flex flex-wrap gap-2">
        {questions.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onAction?.("suggested", q)}
            className="rounded-[6px] border border-primary/20 bg-accent/60 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-accent"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
