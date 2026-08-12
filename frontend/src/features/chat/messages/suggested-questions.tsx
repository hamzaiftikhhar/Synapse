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
  if (!questions.length) return null;

  return (
    <div className="flex flex-wrap gap-2 pl-9">
      {questions.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onAction?.("suggested", q)}
          className="synapse-chat-chip rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
