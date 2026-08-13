import type { AppointmentSource, AppointmentStatus } from "@/types/api";

export const APPOINTMENT_STATUSES: AppointmentStatus[] = [
  "pending",
  "confirmed",
  "completed",
  "no_show",
  "cancelled",
  "rescheduled",
];

export const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  confirmed: "Confirmed",
  completed: "Completed",
  no_show: "No-show",
  cancelled: "Cancelled",
  rescheduled: "Rescheduled",
};

export const STATUS_BADGE_VARIANT: Record<
  string,
  "success" | "warning" | "destructive" | "info" | "secondary"
> = {
  confirmed: "success",
  pending: "warning",
  cancelled: "destructive",
  completed: "info",
  no_show: "destructive",
  rescheduled: "secondary",
};

export const BOOKING_SOURCES: AppointmentSource[] = [
  "admin",
  "phone",
  "walk_in",
  "chatbot",
  "import",
];

export const SOURCE_LABEL: Record<string, string> = {
  admin: "Front desk",
  phone: "Phone",
  walk_in: "Walk-in",
  chatbot: "Chatbot",
  import: "Import",
};

export const CREATE_SOURCES: AppointmentSource[] = ["admin", "phone", "walk_in"];
