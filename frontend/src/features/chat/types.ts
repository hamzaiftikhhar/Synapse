/** Actions returned by the backend in `meta.actions` or `meta.persistent_actions`. */
export type BackendAction = {
  id: string;
  label: string;
  short_label?: string;
  icon?: string;
  variant?: "message" | "action" | "emergency";
  filled?: boolean;
  behavior?: "message" | "open_url" | "call";
  message?: string;
  url?: string;
  href?: string;
  phone?: string;
};
