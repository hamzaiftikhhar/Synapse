"use client";

import { BookingWizard } from "@/features/booking/booking-wizard";
import type { BookingStepPayload } from "@/types/api";
import { cn } from "@/lib/utils";

export type BookingInlineCardProps = {
  clinicSlug: string;
  payload?: Record<string, unknown>;
  active?: boolean;
  onConfirmed?: (payload: BookingStepPayload) => void;
  onDismiss?: () => void;
};

export function BookingInlineCard({
  clinicSlug,
  payload,
  active = true,
  onConfirmed,
  onDismiss,
}: BookingInlineCardProps) {
  const reason =
    (typeof payload?.reason === "string" && payload.reason) ||
    (typeof payload?.message === "string" && payload.message) ||
    "I would like to book an appointment";

  return (
    <div
      className={cn(
        "synapse-chat-msg ml-9 max-w-[min(100%,28rem)] overflow-hidden rounded-[18px] border border-border/80 bg-white shadow-[0_2px_12px_rgb(11_14_46/0.06)]",
        !active && "opacity-90"
      )}
    >
      <BookingWizard
        clinicSlug={clinicSlug}
        initialMessage={reason}
        specialtyId={
          typeof payload?.specialty_id === "string"
            ? payload.specialty_id
            : null
        }
        specialtyName={
          typeof payload?.specialty_name === "string"
            ? payload.specialty_name
            : null
        }
        doctorId={
          typeof payload?.doctor_id === "string" ? payload.doctor_id : null
        }
        doctorName={
          typeof payload?.doctor_name === "string" ? payload.doctor_name : null
        }
        active={active}
        onConfirmed={onConfirmed}
        onDismiss={onDismiss}
      />
    </div>
  );
}
