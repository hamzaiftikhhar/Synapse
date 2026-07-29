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
import { clearStaffTokens } from "@/lib/api/client";
import { STORAGE_KEYS } from "@/constants";
import { authService } from "@/services";
import { queryKeys } from "@/hooks/api";
import type { Clinic, StaffLoginInput, User } from "@/types/api";

type AuthState = {
  user: User | null;
  clinic: Clinic | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (input: StaffLoginInput, remember?: boolean) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
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
  const [isLoading, setIsLoading] = useState(true);

  const refreshMe = useCallback(async () => {
    if (!hasStoredToken()) {
      setUser(null);
      setClinic(null);
      setIsLoading(false);
      return;
    }
    try {
      const data = await authService.me();
      setUser(data.user);
      setClinic(data.clinic);
      qc.setQueryData(queryKeys.me, data);
    } catch {
      clearStaffTokens();
      setUser(null);
      setClinic(null);
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
      qc.setQueryData(queryKeys.me, {
        user: data.user,
        clinic: data.clinic,
      });
    },
    [qc]
  );

  const logout = useCallback(() => {
    authService.logout();
    setUser(null);
    setClinic(null);
    qc.clear();
  }, [qc]);

  const value = useMemo(
    () => ({
      user,
      clinic,
      isLoading,
      isAuthenticated: Boolean(user),
      login,
      logout,
      refreshMe,
    }),
    [user, clinic, isLoading, login, logout, refreshMe]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
