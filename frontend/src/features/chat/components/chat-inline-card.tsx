import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Shared width/position wrapper for chat-message cards (doctor, insurance,
 * service, booking wizard) — the one place that owns "how wide is a card in
 * the chat stream", so it can't drift out of sync between card types.
 * ml-9 aligns with the assistant avatar offset used by text bubbles and by
 * ContextActionChips' pl-9.
 */
export function ChatInlineCard({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("synapse-chat-msg ml-9 max-w-[min(100%,28rem)]", className)}>
      {children}
    </div>
  );
}
