"use client";

import type { ChatActionHandler, ChatMessage } from "@/types/chat";
import { ContextActionChips } from "@/features/chat/components/action-buttons";
import type { BackendAction } from "@/features/chat/types";
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
import { ConfirmationCard } from "./confirmation-card";
import { ClinicLocationCard } from "./clinic-location-card";
import { ImageMessage } from "./image-message";

export function MessageRenderer({
  message,
  onAction,
  onBackendAction,
  showContextActions,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
  onBackendAction?: (action: BackendAction) => void;
  showContextActions?: boolean;
}) {
  let body: React.ReactNode = null;

  switch (message.type) {
    case "text":
    case "system":
      body = <TextMessage message={message} />;
      break;
    case "typing":
      body = <TypingIndicator />;
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
        />
      );
      break;
    case "insurance_cards":
      body = (
        <InsuranceCards
          plans={(message.payload?.plans as never[]) || []}
          onAction={onAction}
        />
      );
      break;
    case "service_cards":
      body = (
        <ServiceCards
          services={(message.payload?.services as never[]) || []}
          onAction={onAction}
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
      body = <TextMessage message={{ ...message, type: "text" }} />;
  }

  const payloadActions = Array.isArray(message.payload?.actions)
    ? (message.payload.actions as BackendAction[])
    : [];

  return (
    <div className="w-full">
      {body}
      {showContextActions &&
      payloadActions.length > 0 &&
      onBackendAction &&
      message.role === "assistant" ? (
        <ContextActionChips
          actions={payloadActions}
          onAction={onBackendAction}
        />
      ) : null}
    </div>
  );
}
