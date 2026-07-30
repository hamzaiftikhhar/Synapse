"use client";

import { CheckCircle2 } from "lucide-react";
import type { ChatMessage } from "@/types/chat";

export function ConfirmationCard({ message }: { message: ChatMessage }) {
  const code = message.payload?.confirmation_code as string | undefined;
  const summary = message.payload?.slot_summary as string | undefined;
  return (
    <div className="rounded-[6px] border border-primary/20 bg-accent/50 p-4">
      <div className="flex items-start gap-2">
        <CheckCircle2 className="mt-0.5 size-4 text-primary" />
        <div>
          <p className="text-sm font-semibold text-navy">
            {message.content || "Appointment confirmed"}
          </p>
          {summary ? (
            <p className="mt-1 text-xs text-muted-foreground">{summary}</p>
          ) : null}
          {code ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Confirmation code:{" "}
              <span className="font-mono text-foreground">{code}</span>
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
