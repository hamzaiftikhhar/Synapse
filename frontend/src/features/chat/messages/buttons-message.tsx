"use client";

import { ButtonChips } from "@/features/chat/components/action-buttons";
import type { BackendAction } from "@/features/chat/types";
import type { ChatActionHandler, ChatMessage } from "@/types/chat";

export function ButtonsMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const buttons = (message.payload?.buttons as BackendAction[]) || [];
  if (!buttons.length || !onAction) return null;
  return <ButtonChips buttons={buttons} onAction={onAction} />;
}
