export const CHART = {
  purple: "#7C3AED",
  purpleFill: "rgba(124, 58, 237, 0.14)",
  purpleLight: "#8B5CF6",
  green: "#16A34A",
  greenFill: "rgba(22, 163, 74, 0.12)",
  red: "#EF4444",
  amber: "#F59E0B",
  blue: "#3B82F6",
  gray: "#6B7280",
  track: "rgba(15, 23, 42, 0.06)",
} as const;

/** Appointment status — high-chroma clinical dots, not muddy ochre/slate. */
export const STATUS_COLOR: Record<string, string> = {
  confirmed: "#3D7EFF",
  pending: "#FF9F1C",
  completed: "#22C55E",
  cancelled: "#FF5A5F",
  no_show: "#8B95A7",
  rescheduled: "#7B6CFF",
};

export const RANGE_OPTIONS = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
  { value: "6m", label: "6 months" },
  { value: "12m", label: "12 months" },
] as const;

export type AnalyticsRange = (typeof RANGE_OPTIONS)[number]["value"];
