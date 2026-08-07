"use client";

import { BookingWizard } from "@/features/booking/booking-wizard";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import type { BookingStepPayload } from "@/types/api";
import { cn } from "@/lib/utils";

export type BookingInlineCardProps = {
  clinicSlug: string;
  payload?: Record<string, unknown>;
  active?: boolean;
  onConfirmed?: (payload: BookingStepPayload) => void;
  onDismiss?: () => void;
  onStarted?: (bookingId: string) => void;
};

export function BookingInlineCard({
  clinicSlug,
  payload,
  active = true,
  onConfirmed,
  onDismiss,
  onStarted,
}: BookingInlineCardProps) {
  const reason =
    (typeof payload?.reason === "string" && payload.reason) ||
    (typeof payload?.message === "string" && payload.message) ||
    "I would like to book an appointment";

  return (
    <ChatInlineCard
      className={cn(
        "overflow-hidden rounded-[18px] border border-border/80 bg-white shadow-[0_2px_12px_rgb(11_14_46/0.06)]",
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
        onStarted={onStarted}
      />
    </ChatInlineCard>
  );
}
