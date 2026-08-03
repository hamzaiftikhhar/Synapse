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
import { clearStaffTokens, getActiveTenant, setActiveTenant } from "@/lib/api/client";
import { STORAGE_KEYS } from "@/constants";
import { authService } from "@/services";
import { queryKeys } from "@/hooks/api";
import type { Clinic, StaffLoginInput, Tenant, User } from "@/types/api";

type AuthState = {
  user: User | null;
  clinic: Clinic | null;
  tenant: string | null;
  tenants: Tenant[];
  canExitClinic: boolean;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (input: StaffLoginInput, remember?: boolean) => Promise<Awaited<ReturnType<typeof authService.login>>>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  selectTenant: (slug: string) => Promise<void>;
  enterClinic: (slug: string) => Promise<void>;
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
      return;
    }
    try {
      const data = await authService.me();
      setUser(data.user);
      setClinic(data.clinic);
      setTenant(data.tenant ?? data.clinic?.slug ?? getActiveTenant());
      setTenants(data.tenants ?? []);
      setCanExitClinic(Boolean(data.can_exit_clinic));
      if (data.tenant) setActiveTenant(data.tenant);
      else if (data.clinic?.slug && data.user.role !== "SUPER_ADMIN") {
        setActiveTenant(data.clinic.slug);
      }
      qc.setQueryData(queryKeys.me, data);
    } catch {
      clearStaffTokens();
      setUser(null);
      setClinic(null);
      setTenant(null);
      setTenants([]);
      setCanExitClinic(false);
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
      setUser(data.user);
      setClinic(data.clinic);
      setTenant(data.tenant ?? data.clinic?.slug ?? null);
      setTenants(data.tenants ?? []);
      setCanExitClinic(false);
      qc.setQueryData(queryKeys.me, {
        user: data.user,
        clinic: data.clinic,
        tenant: data.tenant,
        tenants: data.tenants ?? [],
      });
      return data;
    },
    [qc]
  );

  const selectTenant = useCallback(
    async (slug: string) => {
      const data = await authService.selectTenant(slug);
      setUser(data.user);
      setClinic(data.clinic);
      setTenant(data.tenant ?? slug);
      setTenants(data.tenants ?? []);
      await refreshMe();
    },
    [refreshMe]
  );

  const enterClinic = useCallback(
    async (slug: string) => {
      const data = await authService.enterClinic(slug);
      setClinic(data.clinic);
      setTenant(data.tenant);
      setCanExitClinic(true);
      await refreshMe();
    },
    [refreshMe]
  );

  const exitClinic = useCallback(async () => {
    await authService.exitClinic();
    setClinic(null);
    setTenant(null);
    setCanExitClinic(false);
    await refreshMe();
  }, [refreshMe]);

  const logout = useCallback(() => {
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
