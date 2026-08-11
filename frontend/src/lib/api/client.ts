import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";
import { STORAGE_KEYS } from "@/constants";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  // Match widget budget — staff chatbot also runs NLU + RAG + response LLM.
  timeout: 90_000,
});

function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return (
    localStorage.getItem(STORAGE_KEYS.accessToken) ??
    sessionStorage.getItem(STORAGE_KEYS.accessToken)
  );
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return (
    localStorage.getItem(STORAGE_KEYS.refreshToken) ??
    sessionStorage.getItem(STORAGE_KEYS.refreshToken)
  );
}

export function persistStaffTokens(
  access: string,
  refresh: string,
  remember: boolean
) {
  const store = remember ? localStorage : sessionStorage;
  const other = remember ? sessionStorage : localStorage;
  store.setItem(STORAGE_KEYS.accessToken, access);
  store.setItem(STORAGE_KEYS.refreshToken, refresh);
  other.removeItem(STORAGE_KEYS.accessToken);
  other.removeItem(STORAGE_KEYS.refreshToken);
  localStorage.setItem(STORAGE_KEYS.rememberMe, remember ? "1" : "0");
}

export function clearStaffTokens() {
  localStorage.removeItem(STORAGE_KEYS.accessToken);
  localStorage.removeItem(STORAGE_KEYS.refreshToken);
  sessionStorage.removeItem(STORAGE_KEYS.accessToken);
  sessionStorage.removeItem(STORAGE_KEYS.refreshToken);
  localStorage.removeItem(STORAGE_KEYS.activeTenant);
}

export function getActiveTenant(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(STORAGE_KEYS.activeTenant);
}

export function setActiveTenant(tenant: string | null) {
  if (typeof window === "undefined") return;
  if (tenant) {
    localStorage.setItem(STORAGE_KEYS.activeTenant, tenant);
  } else {
    localStorage.removeItem(STORAGE_KEYS.activeTenant);
  }
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  const tenant = getActiveTenant();
  if (tenant) {
    config.headers["X-Tenant-ID"] = tenant;
  }
  return config;
});

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  try {
    const { data } = await axios.post(`${API_BASE}/auth/refresh`, {
      refresh_token: refresh,
    });
    const remember = localStorage.getItem(STORAGE_KEYS.rememberMe) === "1";
    persistStaffTokens(data.access_token, data.refresh_token, remember);
    // Keep client tenant aligned with refreshed JWT tenant claim
    if (data.tenant) {
      setActiveTenant(data.tenant);
    } else if (data.clinic?.slug) {
      setActiveTenant(data.clinic.slug);
    }
    // Super Admin platform mode: refresh may clear tenant — respect JWT
    if (data.user?.role === "SUPER_ADMIN" && !data.tenant && !data.clinic) {
      setActiveTenant(null);
    }
    return data.access_token as string;
  } catch {
    clearStaffTokens();
    return null;
  }
}

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null;
      });
      const token = await refreshPromise;
      if (token) {
        original.headers.Authorization = `Bearer ${token}`;
        const tenant = getActiveTenant();
        if (tenant) {
          original.headers["X-Tenant-ID"] = tenant;
        } else {
          delete original.headers["X-Tenant-ID"];
        }
        return api(original);
      }
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
      }
    }
    return Promise.reject(error);
  }
);

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as
      | { detail?: string; message?: string }
      | undefined;
    if (typeof data?.detail === "string") return data.detail;
    if (typeof data?.message === "string") return data.message;
    if (error.message) return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

/** Separate client for patient/widget JWT (not staff). */
export const widgetApi = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  // Safety net for rare RAG turns; SQL/direct lanes should finish well under this.
  timeout: 60_000,
});

export function setPatientToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) {
    sessionStorage.setItem(STORAGE_KEYS.patientAccessToken, token);
  } else {
    sessionStorage.removeItem(STORAGE_KEYS.patientAccessToken);
  }
}

export function getPatientToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(STORAGE_KEYS.patientAccessToken);
}

widgetApi.interceptors.request.use((config) => {
  const token = getPatientToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
