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
  const isSystem = message.role === "system" || message.type === "system";
  const streaming = Boolean(message.payload?.streaming);

  if (isSystem) {
    return (
      <div className="synapse-chat-msg flex justify-start py-1 pl-9">
        <p className="max-w-[min(100%,28rem)] rounded-xl border border-amber-200/80 bg-amber-50 px-3.5 py-2.5 text-left text-xs leading-relaxed text-amber-900">
          {message.content}
        </p>
      </div>
    );
  }

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
