export type ChatMessageType =
  | "text"
  | "quick_replies"
  | "buttons"
  | "cards"
  | "doctor_cards"
  | "insurance_cards"
  | "service_cards"
  | "specialty_cards"
  | "calendar"
  | "date_picker"
  | "time_slots"
  | "appointment_form"
  | "appointments"
  | "verify_identity"
  | "booking_wizard"
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
  photo_url?: string;
  languages?: string[];
  accepting?: boolean;
  specialties?: string[];
  /** Message to send when the user selects this doctor (from backend). */
  select_message?: string;
  message?: string;
};

export type InsuranceCardData = {
  id?: string;
  name: string;
  plan?: string;
  notes?: string;
  is_accepted?: boolean;
  select_message?: string;
};

export type ServiceCardData = {
  id?: string;
  name: string;
  description?: string;
  duration_min?: number;
  price_cents?: number | null;
  category?: string;
  select_message?: string;
};

export type SpecialtyCardData = {
  id?: string;
  name: string;
  description?: string;
  doctor_count?: number;
};

export type TimeSlotData = {
  id: string;
  label: string;
  start: string;
  end?: string;
  date?: string;
  time?: string;
  doctor?: string;
  doctor_id?: string;
};

export type AppointmentCardData = {
  id: string;
  doctor: string;
  doctor_id?: string;
  service?: string;
  start_time: string;
  end_time?: string;
  /** Clinic-local 12-hour label from the backend, e.g. "Fri 14 Aug, 12:00 AM". */
  when?: string;
  status?: string;
  confirmation_code?: string;
};

export type MainMenuItem = {
  id: string;
  label: string;
  prompt: string;
  description?: string;
  icon?: string;
};
