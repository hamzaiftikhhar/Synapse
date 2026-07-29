"use client";

import { MapPin } from "lucide-react";
import type { ChatMessage } from "@/types/chat";

export function ClinicLocationCard({ message }: { message: ChatMessage }) {
  const name = (message.payload?.name as string) || "Clinic";
  const address = (message.payload?.address as string) || message.content || "";
  const phone = message.payload?.phone as string | undefined;
  return (
    <div className="rounded-[6px] border border-border bg-white p-3">
      <div className="flex gap-2">
        <MapPin className="mt-0.5 size-4 text-primary" />
        <div>
          <p className="text-sm font-semibold text-navy">{name}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{address}</p>
          {phone ? <p className="mt-1 text-xs text-foreground">{phone}</p> : null}
        </div>
      </div>
    </div>
  );
}
