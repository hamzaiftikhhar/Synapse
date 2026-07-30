export type ChatMessageType =
  | "text"
  | "quick_replies"
  | "buttons"
  | "cards"
  | "doctor_cards"
  | "insurance_cards"
  | "service_cards"
  | "calendar"
  | "date_picker"
  | "time_slots"
  | "appointment_form"
  | "confirmation"
  | "clinic_location"
  | "image"
  | "typing"
  | "suggested_questions"
  | "main_menu"
  | "system";

export type ChatRole = "user" | "assistant" | "system";

export type ChatActionHandler = (action: string, data?: unknown) => void;

export type ChatMessage = {
  id: string;
  role: ChatRole;
  type: ChatMessageType;
  content?: string;
  createdAt: string;
  payload?: Record<string, unknown>;
};

export type DoctorCardData = {
  id?: string;
  name: string;
  title?: string;
  bio?: string;
  languages?: string[];
  accepting?: boolean;
  /** Message to send when the user selects this doctor (from backend). */
  select_message?: string;
  message?: string;
};

export type InsuranceCardData = {
  id?: string;
  name: string;
  plan?: string;
  notes?: string;
};

export type ServiceCardData = {
  id?: string;
  name: string;
  description?: string;
  duration_min?: number;
  price_cents?: number | null;
};

export type TimeSlotData = {
  id: string;
  label: string;
  start: string;
};

export type MainMenuItem = {
  id: string;
  label: string;
  prompt: string;
  description?: string;
  icon?: string;
};
