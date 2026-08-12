"use client";

import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
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
    <ChatInlineCard className="grid gap-2">
      {cards.map((c, i) => (
        <button
          key={c.id || i}
          type="button"
          onClick={() => {
            const msg =
              (typeof c.action === "string" && c.action) ||
              (c as { select_message?: string }).select_message;
            if (msg) onAction?.("suggested", msg);
          }}
          className="rounded-[18px] border border-border/80 bg-card p-3 text-left shadow-[0_2px_12px_rgb(11_14_46/0.06)] hover:bg-accent/40"
        >
          <p className="text-sm font-semibold text-navy">{c.title}</p>
          {c.description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{c.description}</p>
          ) : null}
        </button>
      ))}
    </ChatInlineCard>
  );
}
