"use client";

import type { ChatActionHandler, ChatMessage } from "@/types/chat";

type CardItem = { id?: string; title: string; description?: string; action?: string };

export function CardsMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const cards = (message.payload?.cards as CardItem[]) || [];
  return (
    <div className="grid gap-2">
      {cards.map((c, i) => (
        <button
          key={c.id || i}
          type="button"
          onClick={() => onAction?.(c.action || "card", c)}
          className="rounded-[6px] border border-border bg-white p-3 text-left hover:bg-accent/40"
        >
          <p className="text-sm font-semibold text-navy">{c.title}</p>
          {c.description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{c.description}</p>
          ) : null}
        </button>
      ))}
    </div>
  );
}
