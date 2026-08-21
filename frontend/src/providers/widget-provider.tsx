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
import { STORAGE_KEYS } from "@/constants";
import { widgetService } from "@/services";
import type { WidgetConfig } from "@/types/api";

export type AssistantMode = "marketing" | "clinic" | "staff";

type WidgetContextValue = {
  mode: AssistantMode;
  clinicSlug: string | null;
  config: WidgetConfig | null;
  sessionToken: string | null;
  setSessionToken: (token: string | null) => void;
  /**
   * The anonymous ChatVisitor's stable id — localStorage (not
   * sessionStorage, unlike sessionToken above), so it survives a browser
   * restart. Never invented client-side: only ever set from a value the
   * backend returned (either /chat/resume or a guest message's
   * meta.visitor_id), so its mere presence is exactly the signal used to
   * decide whether opening the widget should call /chat/resume at all.
   */
  visitorId: string | null;
  setVisitorId: (id: string | null) => void;
  isLoading: boolean;
};

const WidgetContext = createContext<WidgetContextValue | null>(null);

const SESSION_KEY = "synapse_widget_session";

export function WidgetProvider({
  children,
  mode,
  clinicSlug,
}: {
  children: ReactNode;
  mode: AssistantMode;
  clinicSlug?: string | null;
}) {
  const [config, setConfig] = useState<WidgetConfig | null>(null);
  const [sessionToken, setSessionTokenState] = useState<string | null>(null);
  const [visitorId, setVisitorIdState] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(mode === "clinic" && Boolean(clinicSlug));

  const storageKey = clinicSlug ? `${SESSION_KEY}_${clinicSlug}` : SESSION_KEY;
  const visitorStorageKey = clinicSlug
    ? `${STORAGE_KEYS.chatVisitor}_${clinicSlug}`
    : STORAGE_KEYS.chatVisitor;

  const setSessionToken = useCallback(
    (token: string | null) => {
      setSessionTokenState(token);
      if (typeof window === "undefined") return;
      if (token) sessionStorage.setItem(storageKey, token);
      else sessionStorage.removeItem(storageKey);
    },
    [storageKey]
  );

  const setVisitorId = useCallback(
    (id: string | null) => {
      setVisitorIdState(id);
      if (typeof window === "undefined") return;
      if (id) localStorage.setItem(visitorStorageKey, id);
      else localStorage.removeItem(visitorStorageKey);
    },
    [visitorStorageKey]
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = sessionStorage.getItem(storageKey);
    if (saved) setSessionTokenState(saved);
  }, [storageKey]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = localStorage.getItem(visitorStorageKey);
    setVisitorIdState(saved || null);
  }, [visitorStorageKey]);

  useEffect(() => {
    if (mode !== "clinic" || !clinicSlug) {
      setConfig(null);
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    widgetService
      .getConfig(clinicSlug)
      .then((c) => {
        if (!cancelled) setConfig(c);
      })
      .catch(() => {
        if (!cancelled) setConfig(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [mode, clinicSlug]);

  const value = useMemo(
    () => ({
      mode,
      clinicSlug: clinicSlug ?? null,
      config,
      sessionToken,
      setSessionToken,
      visitorId,
      setVisitorId,
      isLoading,
    }),
    [mode, clinicSlug, config, sessionToken, setSessionToken, visitorId, setVisitorId, isLoading]
  );

  return (
    <WidgetContext.Provider value={value}>{children}</WidgetContext.Provider>
  );
}

export function useWidget() {
  const ctx = useContext(WidgetContext);
  if (!ctx) {
    return {
      mode: "marketing" as AssistantMode,
      clinicSlug: null,
      config: null,
      sessionToken: null,
      setSessionToken: () => {},
      visitorId: null,
      setVisitorId: () => {},
      isLoading: false,
    };
  }
  return ctx;
}
