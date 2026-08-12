"use client";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import type { ChatActionHandler, ChatMessage } from "@/types/chat";

export function DatePickerMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const [value, setValue] = useState(String(message.payload?.value || ""));
  return (
    <div className="flex items-center gap-2 rounded-[6px] border border-border bg-card p-3">
      <Input
        type="date"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="h-8 rounded-[6px]"
      />
      <Button
        size="sm"
        className="rounded-[6px]"
        onClick={() => value && onAction?.("select_date", value)}
      >
        Confirm
      </Button>
    </div>
  );
}
