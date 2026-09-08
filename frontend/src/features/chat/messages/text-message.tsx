"use client";

import { cn } from "@/lib/utils";
import { RobotAvatar } from "@/features/chat/components/robot-avatar";
import {
  BotMetaRow,
  formatMessageTime,
} from "@/features/chat/components/chat-chrome";
import type { ChatMessage } from "@/types/chat";

export function TextMessage({
  message,
  assistantName,
}: {
  message: ChatMessage;
  assistantName?: string;
}) {
  const isUser = message.role === "user";
  // Ordinary system notices (status confirmations, emergency safety
  // guidance) used to render in an amber "warning" box regardless of
  // what they actually said — researched before this change: that
  // color is reserved for "unintended but not dangerous" effects, not a
  // routine "appointment cancelled" confirmation, and reads as alarming
  // for the rare emergency case that isn't already deduplicated against
  // the main reply (appendSafetyBanner in message-parser.ts). Those now
  // render exactly like any other assistant reply. Only a genuine
  // failure (systemErrorMessage) keeps a distinguishing accent, done as
  // a subtle tint on the same bubble shape, not a separate colored box.
  const isError = message.type === "system" && message.payload?.variant === "error";
  const streaming = Boolean(message.payload?.streaming);

  return (
    <div
      className={cn(
        "synapse-chat-msg flex gap-2.5",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      {!isUser ? (
        <RobotAvatar
          size="sm"
          className="mt-5 shrink-0 rounded-full bg-primary"
        />
      ) : null}
      <div className={cn("min-w-0 max-w-[85%]", isUser && "items-end")}>
        {!isUser ? (
          <BotMetaRow
            name={assistantName}
            time={formatMessageTime(message.createdAt)}
          />
        ) : null}
        <div
          className={cn(
            "px-3.5 py-2.5 text-sm leading-relaxed synapse-chat-bubble",
            isUser
              ? "synapse-chat-bubble--user bg-primary text-primary-foreground shadow-sm"
              : isError
                ? "synapse-chat-bubble--bot border border-destructive/25 bg-destructive/5 text-foreground shadow-sm"
                : "synapse-chat-bubble--bot border border-border/80 bg-card text-foreground shadow-sm",
            streaming && !isUser && "synapse-stream-cursor"
          )}
        >
          {message.content}
        </div>
        {isUser ? (
          <p className="mt-1 px-1 text-right text-[10px] text-muted-foreground">
            {formatMessageTime(message.createdAt)}
          </p>
        ) : null}
      </div>
    </div>
  );
}
