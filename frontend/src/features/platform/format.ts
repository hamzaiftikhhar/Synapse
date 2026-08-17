const VARIANT: Record<string, "success" | "warning" | "destructive" | "info" | "secondary" | "outline"> = {
  active: "success",
  trialing: "info",
  pending: "warning",
  reviewing: "warning",
  incomplete: "warning",
  past_due: "destructive",
  paused: "secondary",
  canceled: "outline",
  cancelled: "outline",
  rejected: "destructive",
  converted: "success",
  approved: "success",
  onboarding: "info",
  suspended: "destructive",
  indexed: "success",
  chunked: "info",
  processing: "warning",
  failed: "destructive",
};

export function toneFor(status: string): "success" | "warning" | "destructive" | "info" | "secondary" | "outline" {
  return VARIANT[status] ?? "secondary";
}

export function roleLabel(role: string) {
  if (role === "SUPER_ADMIN") return "Super admin";
  if (role === "CLINIC_ADMIN") return "Clinic admin";
  if (role === "STAFF") return "Staff";
  return role;
}

export function formatWhen(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatCents(cents: number | null | undefined, currency = "USD") {
  if (cents == null) return "—";
  return (cents / 100).toLocaleString(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

export function humanAction(action: string) {
  return action.replaceAll("_", " ");
}
