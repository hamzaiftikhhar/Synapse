"use client";

import type { ChatActionHandler, ChatMessage } from "@/types/chat";
import { ContextActionChips } from "@/features/chat/components/action-buttons";
import type { BackendAction } from "@/features/chat/types";
import { BookingInlineCard } from "@/features/booking";
import type { BookingStepPayload } from "@/types/api";
import { TextMessage } from "./text-message";
import { TypingIndicator } from "./typing-indicator";
import { QuickReplies } from "./quick-replies";
import { ButtonsMessage } from "./buttons-message";
import { SuggestedQuestions } from "./suggested-questions";
import { MainMenuMessage } from "./main-menu";
import { DoctorCards } from "./doctor-card";
import { InsuranceCards } from "./insurance-card";
import { ServiceCards } from "./service-card";
import { CardsMessage } from "./cards-message";
import { CalendarMessage } from "./calendar-message";
import { DatePickerMessage } from "./date-picker-message";
import { TimeSlotsMessage } from "./time-slots-message";
import { AppointmentFormMessage } from "./appointment-form-message";
import { AppointmentCards } from "./appointment-card";
import { VerifyIdentity } from "./verify-identity";
import { ConfirmationCard } from "./confirmation-card";
import { ClinicLocationCard } from "./clinic-location-card";
import { ImageMessage } from "./image-message";

export function MessageRenderer({
  message,
  onAction,
  onBackendAction,
  showContextActions,
  assistantName,
  clinicSlug,
  sessionToken,
  bookingWizardActive,
  onBookingConfirmed,
  onBookingDismiss,
  onBookingStarted,
  onIdentityVerified,
  onSessionToken,
  typingHint,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
  onBackendAction?: (action: BackendAction) => void;
  showContextActions?: boolean;
  assistantName?: string;
  clinicSlug?: string;
  sessionToken?: string | null;
  bookingWizardActive?: boolean;
  onBookingConfirmed?: (payload: BookingStepPayload) => void;
  onBookingDismiss?: (messageId: string) => void;
  onBookingStarted?: (messageId: string, bookingId: string) => void;
  onIdentityVerified?: (messageId: string, sessionToken: string) => void;
  onSessionToken?: (token: string) => void;
  /** Last user message — used for calm typing status copy. */
  typingHint?: string;
}) {
  let body: React.ReactNode = null;

  switch (message.type) {
    case "text":
    case "system":
      body = <TextMessage message={message} assistantName={assistantName} />;
      break;
    case "typing":
      body = (
        <TypingIndicator
          assistantName={assistantName}
          userHint={typingHint}
        />
      );
      break;
    case "quick_replies":
      body = <QuickReplies message={message} onAction={onAction} />;
      break;
    case "buttons":
      body = <ButtonsMessage message={message} onAction={onAction} />;
      break;
    case "suggested_questions":
      body = <SuggestedQuestions message={message} onAction={onAction} />;
      break;
    case "main_menu":
      body = <MainMenuMessage message={message} onAction={onAction} />;
      break;
    case "doctor_cards":
      body = (
        <DoctorCards
          doctors={(message.payload?.doctors as never[]) || []}
          onAction={onAction}
          messageId={message.id}
        />
      );
      break;
    case "insurance_cards":
      body = (
        <InsuranceCards
          plans={(message.payload?.plans as never[]) || []}
          onAction={onAction}
          clinicSlug={clinicSlug}
        />
      );
      break;
    case "service_cards":
      body = (
        <ServiceCards
          services={(message.payload?.services as never[]) || []}
          onAction={onAction}
          messageId={message.id}
        />
      );
      break;
    case "cards":
      body = <CardsMessage message={message} onAction={onAction} />;
      break;
    case "calendar":
      body = <CalendarMessage message={message} onAction={onAction} />;
      break;
    case "date_picker":
      body = <DatePickerMessage message={message} onAction={onAction} />;
      break;
    case "time_slots":
      body = <TimeSlotsMessage message={message} onAction={onAction} />;
      break;
    case "appointment_form":
      body = <AppointmentFormMessage message={message} onAction={onAction} />;
      break;
    case "appointments":
      body = (
        <AppointmentCards
          appointments={(message.payload?.appointments as never[]) || []}
          onAction={onAction}
          completed={Boolean(message.payload?.completed)}
          messageId={message.id}
        />
      );
      break;
    case "verify_identity":
      body = clinicSlug ? (
        <VerifyIdentity
          clinicSlug={clinicSlug}
          sessionToken={sessionToken ?? null}
          onSessionToken={onSessionToken}
          onVerified={(token) => onIdentityVerified?.(message.id, token)}
          completed={Boolean(message.payload?.completed)}
        />
      ) : null;
      break;
    case "booking_wizard":
      body = clinicSlug ? (
        <BookingInlineCard
          clinicSlug={clinicSlug}
          payload={message.payload}
          active={bookingWizardActive !== false}
          onConfirmed={onBookingConfirmed}
          onDismiss={() => onBookingDismiss?.(message.id)}
          onStarted={(bookingId) => onBookingStarted?.(message.id, bookingId)}
        />
      ) : null;
      break;
    case "confirmation":
      body = <ConfirmationCard message={message} />;
      break;
    case "clinic_location":
      body = <ClinicLocationCard message={message} />;
      break;
    case "image":
      body = <ImageMessage message={message} />;
      break;
    default:
      body = (
        <TextMessage
          message={{ ...message, type: "text" }}
          assistantName={assistantName}
        />
      );
  }

  const payloadActions = Array.isArray(message.payload?.actions)
    ? (message.payload.actions as BackendAction[])
    : [];
  const showActions =
    showContextActions &&
    payloadActions.length > 0 &&
    Boolean(onBackendAction) &&
    message.role === "assistant";

  // A message that renders nothing (e.g. a time-slot card that collapsed
  // to null after being picked) must not leave behind an empty flex child
  // here — the message list's `gap-4` applies on both sides of every
  // child regardless of whether it has visible content, so an empty div
  // silently doubles the visual gap between the two real messages around
  // it. Render nothing at all instead of an empty wrapper.
  if (body === null && !showActions) return null;

  return (
    <div className="w-full">
      {body}
      {showActions ? (
        <ContextActionChips
          actions={payloadActions}
          onAction={onBackendAction!}
        />
      ) : null}
    </div>
  );
}
