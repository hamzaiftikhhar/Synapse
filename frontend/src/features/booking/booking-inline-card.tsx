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
        "overflow-hidden rounded-[18px] border border-border/80 bg-card shadow-sm",
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
        serviceId={
          typeof payload?.service_id === "string" ? payload.service_id : null
        }
        serviceName={
          typeof payload?.service_name === "string" ? payload.service_name : null
        }
        slotStart={
          typeof payload?.slot_start === "string" ? payload.slot_start : null
        }
        slotEnd={
          typeof payload?.slot_end === "string" ? payload.slot_end : null
        }
        insuranceName={
          typeof payload?.insurance_name === "string"
            ? payload.insurance_name
            : null
        }
        replacesAppointmentId={
          typeof payload?.replaces_appointment_id === "string"
            ? payload.replaces_appointment_id
            : null
        }
        active={active}
        onConfirmed={onConfirmed}
        onDismiss={onDismiss}
        onStarted={onStarted}
      />
    </ChatInlineCard>
  );
}
