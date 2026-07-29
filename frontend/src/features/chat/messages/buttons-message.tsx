"use client";

import { Button } from "@/components/ui/button";
import type { ChatActionHandler, ChatMessage } from "@/types/chat";

type Btn = { id: string; label: string; variant?: "default" | "outline" };

export function ButtonsMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const buttons = (message.payload?.buttons as Btn[]) || [];
  return (
    <div className="flex flex-wrap gap-2">
      {buttons.map((b) => (
        <Button
          key={b.id}
          size="sm"
          variant={b.variant === "outline" ? "outline" : "default"}
          className="rounded-[6px]"
          onClick={() => onAction?.("button", b)}
        >
          {b.label}
        </Button>
      ))}
    </div>
  );
}
