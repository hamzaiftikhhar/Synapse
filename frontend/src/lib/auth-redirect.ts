import { STORAGE_KEYS } from "@/constants";
import type { Clinic, StaffTokenResponse, Tenant } from "@/types/api";

/** Same-origin relative paths only — never honor an open redirect. */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const path = raw.trim();
  if (!path.startsWith("/") || path.startsWith("//")) return null;
  if (path.includes("://") || path.includes("\\")) return null;
  if (path === "/login" || path.startsWith("/login?")) return null;
  return path;
}

function selectTenantPath(tenants: Tenant[], next: string | null): string {
  const qs = new URLSearchParams();
  if (tenants.length === 1) qs.set("auto", tenants[0].slug);
  if (next) qs.set("next", next);
  const q = qs.toString();
  return q ? `/select-tenant?${q}` : "/select-tenant";
}

/**
 * Clinic staff login does not bind a tenant unless they passed clinic_slug.
 * Blindly following ?next=/dashboard skips /select-tenant and the dashboard
 * then has no clinic context. Super-admin is the exception: /dashboard
 * without a clinic is the platform portal.
 */
export function pathAfterLogin(
  data: StaffTokenResponse,
  nextRaw: string | null
): string {
  const next = safeNextPath(nextRaw);
  const isSuper = data.user.role === "SUPER_ADMIN";
  if (isSuper) {
    if (next && next !== "/dashboard") return next;
    return "/dashboard/platform";
  }
  if (data.clinic) {
    if (data.clinic.status !== "active") return "/onboarding";
    return next ?? "/dashboard";
  }
  const tenants = data.tenants ?? [];
  if (tenants.length === 0) return "/onboarding/create-clinic";
  return selectTenantPath(tenants, next);
}

export function pathAfterTenantSelect(
  clinic: Clinic | null | undefined,
  nextRaw: string | null
): string {
  if (clinic && clinic.status !== "active") return "/onboarding";
  return safeNextPath(nextRaw) ?? "/dashboard";
}

export function markExplicitLogout(): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(STORAGE_KEYS.explicitLogout, "1");
}

export function consumeExplicitLogout(): boolean {
  if (typeof window === "undefined") return false;
  const flagged = sessionStorage.getItem(STORAGE_KEYS.explicitLogout) === "1";
  if (flagged) sessionStorage.removeItem(STORAGE_KEYS.explicitLogout);
  return flagged;
}

export function isExplicitLogout(): boolean {
  if (typeof window === "undefined") return false;
  return sessionStorage.getItem(STORAGE_KEYS.explicitLogout) === "1";
}
