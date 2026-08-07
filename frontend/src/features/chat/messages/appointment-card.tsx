"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import type { AppointmentCardData, ChatActionHandler } from "@/types/chat";

function formatWhen(startIso: string): string {
  const d = new Date(startIso);
  if (Number.isNaN(d.getTime())) return startIso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function AppointmentCard({
  appt,
  onAction,
}: {
  appt: AppointmentCardData;
  onAction?: ChatActionHandler;
}) {
  const [pending, setPending] = useState<"cancel" | "reschedule" | null>(null);

  if (pending) {
    return (
      <div className="rounded-lg border border-border bg-white p-3">
        <p className="text-sm font-medium text-foreground">
          {pending === "cancel"
            ? "Cancel this appointment?"
            : "Reschedule this appointment?"}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {appt.doctor} · {formatWhen(appt.start_time)}
        </p>
        <div className="mt-2.5 flex gap-2">
          <Button
            type="button"
            size="xs"
            variant="outline"
            className="flex-1"
            onClick={() => setPending(null)}
          >
            No, keep it
          </Button>
          <Button
            type="button"
            size="xs"
            variant={pending === "cancel" ? "destructive" : "default"}
            className="flex-1"
            onClick={() =>
              onAction?.(
                pending === "cancel"
                  ? "confirm_cancel_appointment"
                  : "confirm_reschedule_appointment",
                appt
              )
            }
          >
            {pending === "cancel" ? "Yes, cancel" : "Yes, reschedule"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-white p-3">
      <p className="text-sm font-semibold text-foreground">{appt.doctor}</p>
      {appt.service ? (
        <p className="text-xs text-muted-foreground">{appt.service}</p>
      ) : null}
      <p className="mt-1 text-xs text-foreground">{formatWhen(appt.start_time)}</p>
      <div className="mt-2.5 flex gap-2">
        <Button
          type="button"
          size="xs"
          variant="outline"
          className="flex-1"
          onClick={() => setPending("reschedule")}
        >
          Reschedule
        </Button>
        <Button
          type="button"
          size="xs"
          variant="destructive"
          className="flex-1"
          onClick={() => setPending("cancel")}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function AppointmentCards({
  appointments,
  onAction,
}: {
  appointments: AppointmentCardData[];
  onAction?: ChatActionHandler;
}) {
  return (
    <ChatInlineCard className="space-y-2">
      {appointments.map((a) => (
        <AppointmentCard key={a.id} appt={a} onAction={onAction} />
      ))}
    </ChatInlineCard>
  );
}
