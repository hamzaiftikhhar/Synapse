"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { clearStaffTokens, getActiveTenant, setActiveTenant } from "@/lib/api/client";
import { markExplicitLogout } from "@/lib/auth-redirect";
import { STORAGE_KEYS } from "@/constants";
import { authService } from "@/services";
import { queryKeys } from "@/hooks/api";
import type { AcceptInviteInput, Clinic, StaffLoginInput, Tenant, User } from "@/types/api";

type AuthState = {
  user: User | null;
  clinic: Clinic | null;
  tenant: string | null;
  tenants: Tenant[];
  canExitClinic: boolean;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (
    input: StaffLoginInput,
    remember?: boolean
  ) => Promise<Awaited<ReturnType<typeof authService.login>>>;
  acceptInvite: (
    input: AcceptInviteInput
  ) => Promise<Awaited<ReturnType<typeof authService.acceptInvite>>>;
  logout: () => void;
  /** Resolves `true` only if this call actually fetched and applied fresh
   * state — `false` covers both "no token" and "request failed", in which
   * case existing session state was deliberately left untouched (network
   * blips shouldn't log someone out). Callers that need to *confirm* fresh
   * state landed (e.g. right after an action that changed it server-side)
   * should check this rather than assume a resolved promise means success. */
  refreshMe: () => Promise<boolean>;
  selectTenant: (slug: string) => Promise<Awaited<ReturnType<typeof authService.selectTenant>>>;
  enterClinic: (
    slug: string
  ) => Promise<Awaited<ReturnType<typeof authService.enterClinic>>>;
  exitClinic: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

function hasStoredToken() {
  if (typeof window === "undefined") return false;
  return Boolean(
    localStorage.getItem(STORAGE_KEYS.accessToken) ||
      sessionStorage.getItem(STORAGE_KEYS.accessToken)
  );
}

function applyTokenResponse(
  data: Awaited<ReturnType<typeof authService.login>>,
  setters: {
    setUser: (u: User | null) => void;
    setClinic: (c: Clinic | null) => void;
    setTenant: (t: string | null) => void;
    setTenants: (t: Tenant[]) => void;
    setCanExitClinic: (v: boolean) => void;
  }
) {
  setters.setUser(data.user);
  setters.setClinic(data.clinic);
  setters.setTenant(data.tenant ?? data.clinic?.slug ?? null);
  setters.setTenants(data.tenants ?? []);
  setters.setCanExitClinic(
    data.user.role === "SUPER_ADMIN" && Boolean(data.clinic)
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [clinic, setClinic] = useState<Clinic | null>(null);
  const [tenant, setTenant] = useState<string | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [canExitClinic, setCanExitClinic] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const refreshMe = useCallback(async () => {
    if (!hasStoredToken()) {
      setUser(null);
      setClinic(null);
      setTenant(null);
      setTenants([]);
      setCanExitClinic(false);
      setIsLoading(false);
      return false;
    }
    try {
      const data = await authService.me();
      setUser(data.user);
      setClinic(data.clinic);
      setTenant(data.tenant ?? data.clinic?.slug ?? getActiveTenant());
      setTenants(data.tenants ?? []);
      setCanExitClinic(Boolean(data.can_exit_clinic));
      if (data.tenant) {
        setActiveTenant(data.tenant);
      } else if (data.user.role === "SUPER_ADMIN" && !data.clinic) {
        // Platform mode — clear stale tenant header
        setActiveTenant(null);
      } else if (data.clinic?.slug && data.user.role !== "SUPER_ADMIN") {
        setActiveTenant(data.clinic.slug);
      }
      qc.setQueryData(queryKeys.me, data);
      return true;
    } catch (err) {
      const status = axios.isAxiosError(err) ? err.response?.status : undefined;
      if (status === 401) {
        clearStaffTokens();
        setUser(null);
        setClinic(null);
        setTenant(null);
        setTenants([]);
        setCanExitClinic(false);
      }
      // Non-401: keep session; caller can retry
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [qc]);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  const login = useCallback(
    async (input: StaffLoginInput, remember = true) => {
      const data = await authService.login(input, remember);
      applyTokenResponse(data, {
        setUser,
        setClinic,
        setTenant,
        setTenants,
        setCanExitClinic,
      });
      qc.setQueryData(queryKeys.me, {
        user: data.user,
        clinic: data.clinic,
        tenant: data.tenant,
        tenants: data.tenants ?? [],
        can_exit_clinic: data.user.role === "SUPER_ADMIN" && Boolean(data.clinic),
      });
      return data;
    },
    [qc]
  );

  const acceptInvite = useCallback(
    async (input: AcceptInviteInput) => {
      const data = await authService.acceptInvite(input);
      applyTokenResponse(data, {
        setUser,
        setClinic,
        setTenant,
        setTenants,
        setCanExitClinic,
      });
      qc.setQueryData(queryKeys.me, {
        user: data.user,
        clinic: data.clinic,
        tenant: data.tenant,
        tenants: data.tenants ?? [],
        can_exit_clinic: false,
      });
      return data;
    },
    [qc]
  );

  /** Drop every cached tenant-scoped response and re-seed `/auth/me`.
   *
   * Tenant-scoped queries (doctors, appointments, analytics, …) are keyed
   * without a clinic dimension — they rely on the `X-Tenant-ID` header alone.
   * `invalidateQueries()` keeps showing the *previous* clinic's data as a
   * placeholder until the refetch lands, which is exactly the "switch didn't
   * take until I clicked something else" bug. Cancel in-flight fetches for
   * the old tenant, clear the cache, then put the fresh me payload back so
   * remounted pages fetch against the new header with an empty slate.
   */
  const resetTenantScopedCache = useCallback(
    async (me: {
      user: User;
      clinic: Clinic | null;
      tenant: string | null;
      tenants: Tenant[];
      can_exit_clinic: boolean;
    }) => {
      await qc.cancelQueries();
      qc.clear();
      qc.setQueryData(queryKeys.me, me);
    },
    [qc]
  );

  const selectTenant = useCallback(async (slug: string) => {
    const data = await authService.selectTenant(slug);
    applyTokenResponse(data, {
      setUser,
      setClinic,
      setTenant,
      setTenants,
      setCanExitClinic,
    });
    await resetTenantScopedCache({
      user: data.user,
      clinic: data.clinic,
      tenant: data.tenant ?? data.clinic?.slug ?? slug,
      tenants: data.tenants ?? [],
      can_exit_clinic: data.user.role === "SUPER_ADMIN" && Boolean(data.clinic),
    });
    return data;
  }, [resetTenantScopedCache]);

  const enterClinic = useCallback(async (slug: string) => {
    const data = await authService.enterClinic(slug);
    applyTokenResponse(data, {
      setUser,
      setClinic,
      setTenant,
      setTenants,
      setCanExitClinic,
    });
    await resetTenantScopedCache({
      user: data.user,
      clinic: data.clinic,
      tenant: data.tenant ?? data.clinic?.slug ?? slug,
      tenants: data.tenants ?? [],
      can_exit_clinic: true,
    });
    return data;
  }, [resetTenantScopedCache]);

  const exitClinic = useCallback(async () => {
    const data = await authService.exitClinic();
    applyTokenResponse(data, {
      setUser,
      setClinic,
      setTenant,
      setTenants,
      setCanExitClinic,
    });
    await resetTenantScopedCache({
      user: data.user,
      clinic: null,
      tenant: null,
      tenants: data.tenants ?? [],
      can_exit_clinic: false,
    });
  }, [resetTenantScopedCache]);

  const logout = useCallback(() => {
    markExplicitLogout();
    authService.logout();
    setUser(null);
    setClinic(null);
    setTenant(null);
    setTenants([]);
    setCanExitClinic(false);
    qc.clear();
  }, [qc]);

  const value = useMemo(
    () => ({
      user,
      clinic,
      tenant,
      tenants,
      canExitClinic,
      isLoading,
      isAuthenticated: Boolean(user),
      login,
      acceptInvite,
      logout,
      refreshMe,
      selectTenant,
      enterClinic,
      exitClinic,
    }),
    [
      user,
      clinic,
      tenant,
      tenants,
      canExitClinic,
      isLoading,
      login,
      acceptInvite,
      logout,
      refreshMe,
      selectTenant,
      enterClinic,
      exitClinic,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
