/**
 * Workspace handoff coordination — enter/switch/exit clinic, login, logout.
 *
 * Mark a handoff *before* async work so one loader covers the UI instantly.
 * Success toasts are stashed and consumed only after destination auth boot.
 */

const ACTIVE_KEY = "synapse_handoff_active";
const TOAST_KEY = "synapse_handoff_toast";
const THEME_KEY = "synapse-dashboard-theme";

export type HandoffToast = {
  type: "success" | "error";
  message: string;
};

export type HandoffActive = {
  label: string;
  at: number;
};

export function readDashboardTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(THEME_KEY);
  return stored === "dark" ? "dark" : "light";
}

export function markHandoffActive(label: string): void {
  if (typeof window === "undefined") return;
  const payload: HandoffActive = { label, at: Date.now() };
  sessionStorage.setItem(ACTIVE_KEY, JSON.stringify(payload));
}

export function peekHandoffActive(): HandoffActive | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(ACTIVE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as HandoffActive;
    if (!parsed?.label || Date.now() - (parsed.at || 0) > 60_000) {
      sessionStorage.removeItem(ACTIVE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearHandoffActive(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(ACTIVE_KEY);
}

export function stashHandoffToast(toast: HandoffToast): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(TOAST_KEY, JSON.stringify({ ...toast, at: Date.now() }));
}

export function consumeHandoffToast(): HandoffToast | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(TOAST_KEY);
    sessionStorage.removeItem(TOAST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as HandoffToast & { at?: number };
    if (!parsed?.message) return null;
    if (parsed.at && Date.now() - parsed.at > 60_000) return null;
    return { type: parsed.type, message: parsed.message };
  } catch {
    return null;
  }
}
