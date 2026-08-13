"use client";

import { useState } from "react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import type { AppointmentCardData, ChatActionHandler } from "@/types/chat";

function formatWhen(appt: AppointmentCardData): string {
  if (appt.when) return appt.when;
  const d = new Date(appt.start_time);
  if (Number.isNaN(d.getTime())) return appt.start_time;
  // Always 12-hour with AM/PM — 24-hour locales otherwise render midnight as "0:00".
  return format(d, "EEE d MMM, h:mm a");
}

type Stage = null | "cancel-confirm" | "reschedule-confirm" | "reschedule-options";

function AppointmentCard({
  appt,
  onAction,
}: {
  appt: AppointmentCardData;
  onAction?: ChatActionHandler;
}) {
  const [stage, setStage] = useState<Stage>(null);

  if (stage === "cancel-confirm") {
    return (
      <div className="rounded-lg border border-border bg-card p-3">
        <p className="text-sm font-medium text-foreground">Cancel appointment?</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {appt.doctor} · {formatWhen(appt)}
        </p>
        <p className="mt-1.5 text-xs text-muted-foreground">
          This appointment will be cancelled.
        </p>
        <div className="mt-2.5 flex gap-2">
          <Button
            type="button"
            size="xs"
            variant="outline"
            className="flex-1"
            onClick={() => setStage(null)}
          >
            Keep Appointment
          </Button>
          <Button
            type="button"
            size="xs"
            variant="destructive"
            className="flex-1"
            onClick={() => onAction?.("confirm_cancel_appointment", appt)}
          >
            Cancel Appointment
          </Button>
        </div>
      </div>
    );
  }

  if (stage === "reschedule-confirm") {
    return (
      <div className="rounded-lg border border-border bg-card p-3">
        <p className="text-sm font-medium text-foreground">Reschedule appointment?</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {appt.doctor} · {formatWhen(appt)}
        </p>
        <div className="mt-2.5 flex gap-2">
          <Button
            type="button"
            size="xs"
            variant="outline"
            className="flex-1"
            onClick={() => setStage(null)}
          >
            No, keep it
          </Button>
          <Button
            type="button"
            size="xs"
            className="flex-1"
            onClick={() => setStage("reschedule-options")}
          >
            Yes, reschedule
          </Button>
        </div>
      </div>
    );
  }

  if (stage === "reschedule-options") {
    return (
      <div className="rounded-lg border border-border bg-card p-3">
        <p className="text-sm font-medium text-foreground">Current provider</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{appt.doctor}</p>
        <div className="mt-2.5 flex flex-col gap-1.5">
          <Button
            type="button"
            size="xs"
            onClick={() => onAction?.("start_reschedule", { ...appt, changeDoctor: false })}
          >
            Keep {appt.doctor}
          </Button>
          <Button
            type="button"
            size="xs"
            variant="outline"
            onClick={() => onAction?.("start_reschedule", { ...appt, changeDoctor: true })}
          >
            Change Doctor
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <p className="text-sm font-semibold text-foreground">{appt.doctor}</p>
      {appt.service ? (
        <p className="text-xs text-muted-foreground">{appt.service}</p>
      ) : null}
      <p className="mt-1 text-xs text-foreground">{formatWhen(appt)}</p>
      <div className="mt-2.5 flex gap-2">
        <Button
          type="button"
          size="xs"
          variant="outline"
          className="flex-1"
          onClick={() => setStage("reschedule-confirm")}
        >
          Reschedule
        </Button>
        <Button
          type="button"
          size="xs"
          variant="destructive"
          className="flex-1"
          onClick={() => setStage("cancel-confirm")}
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
  if (appointments.length === 0) {
    return (
      <ChatInlineCard className="space-y-1 text-center">
        <p className="text-sm font-medium text-foreground">No upcoming appointments</p>
        <p className="text-xs text-muted-foreground">
          We couldn&apos;t find any upcoming appointments for your account.
        </p>
        <Button
          type="button"
          size="xs"
          className="mt-1.5"
          onClick={() => onAction?.("book_appointment", {})}
        >
          Book a New Appointment
        </Button>
      </ChatInlineCard>
    );
  }

  return (
    <ChatInlineCard className="space-y-2">
      {appointments.map((a) => (
        <AppointmentCard key={a.id} appt={a} onAction={onAction} />
      ))}
    </ChatInlineCard>
  );
}
