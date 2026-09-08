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
  readOnly = false,
  inert = false,
  messageId,
}: {
  appt: AppointmentCardData;
  onAction?: ChatActionHandler;
  /** Set for a historical (resumed) appointments list — Cancel/Reschedule
   * must be a deliberate action taken from the *current* state of a real
   * appointment, never a stray click replaying an old turn's snapshot. */
  readOnly?: boolean;
  /** Set once a reschedule wizard has been launched from *this specific*
   * row — same collapse-on-supersede idea as every other card, but
   * row-scoped rather than message-scoped: other appointments still
   * listed in the same card (a patient can have more than one) must stay
   * fully live, only the row that was just acted on retires. */
  inert?: boolean;
  /** Passed through to start_reschedule so the parent can identify which
   * row to retire once a wizard launches from it. */
  messageId?: string;
}) {
  const [stage, setStage] = useState<Stage>(null);

  if (inert) {
    return (
      <div className="rounded-lg border border-border bg-card p-3 text-center">
        <p className="text-sm text-muted-foreground">
          Rescheduling {appt.doctor} ↓
        </p>
      </div>
    );
  }

  if (readOnly) {
    return (
      <div className="rounded-lg border border-border bg-card p-3">
        <p className="text-sm font-semibold text-foreground">{appt.doctor}</p>
        {appt.service ? (
          <p className="text-xs text-muted-foreground">{appt.service}</p>
        ) : null}
        <p className="mt-1 text-xs text-foreground">{formatWhen(appt)}</p>
      </div>
    );
  }

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
        <div className="mt-2.5 flex gap-2">
          <Button
            type="button"
            size="xs"
            className="flex-1"
            onClick={() =>
              onAction?.("start_reschedule", { ...appt, changeDoctor: false, messageId })
            }
          >
            Keep
          </Button>
          <Button
            type="button"
            size="xs"
            variant="outline"
            className="flex-1"
            onClick={() =>
              onAction?.("start_reschedule", { ...appt, changeDoctor: true, messageId })
            }
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
  completed = false,
  cancelledMessage,
  rescheduledIds,
  messageId,
  readOnly = false,
}: {
  appointments: AppointmentCardData[];
  onAction?: ChatActionHandler;
  /** Set once "Book a New Appointment" has already been used from this
   * exact message — same collapse-on-supersede idea as booking_wizard
   * (Phase 22): once that click has launched a wizard, this card
   * shouldn't keep sitting there as a live, re-clickable prompt. */
  completed?: boolean;
  /** Set when this card's list became empty because its one appointment
   * was just cancelled from it — a distinct situation from `completed`
   * (nothing was "started" here). Without this, the emptied card used to
   * fall through to the full "No upcoming appointments" empty state
   * (title + subtitle + "Book a New Appointment" button) *and* a separate
   * "Appointment cancelled" system message appeared right after — two
   * redundant signals for one action, live-confirmed. This replaces both
   * with a single line here instead. */
  cancelledMessage?: string;
  /** Appointment ids a reschedule wizard has already been launched from —
   * row-scoped, not message-scoped, so a patient with more than one
   * upcoming appointment doesn't lose the others just for acting on one. */
  rescheduledIds?: string[];
  messageId?: string;
  /** Set for a historical (resumed) appointments list — see AppointmentCard. */
  readOnly?: boolean;
}) {
  if (appointments.length === 0) {
    if (cancelledMessage) {
      return (
        <ChatInlineCard className="flex items-center gap-2 py-2.5 text-center">
          <p className="text-sm text-muted-foreground">{cancelledMessage}</p>
        </ChatInlineCard>
      );
    }
    if (completed) {
      return (
        <ChatInlineCard className="flex items-center gap-2 py-2.5 text-center">
          <p className="text-sm text-muted-foreground">
            You started booking a new appointment ↓
          </p>
        </ChatInlineCard>
      );
    }
    return (
      <ChatInlineCard className="space-y-1 text-center">
        <p className="text-sm font-medium text-foreground">No upcoming appointments</p>
        <p className="text-xs text-muted-foreground">
          We couldn&apos;t find any upcoming appointments for your account.
        </p>
        {readOnly ? null : (
          <Button
            type="button"
            size="xs"
            className="mt-1.5"
            onClick={() => onAction?.("book_appointment", { messageId })}
          >
            Book a New Appointment
          </Button>
        )}
      </ChatInlineCard>
    );
  }

  return (
    <ChatInlineCard className="space-y-2">
      {appointments.map((a) => (
        <AppointmentCard
          key={a.id}
          appt={a}
          onAction={onAction}
          readOnly={readOnly}
          inert={Boolean(rescheduledIds?.includes(a.id))}
          messageId={messageId}
        />
      ))}
    </ChatInlineCard>
  );
}
