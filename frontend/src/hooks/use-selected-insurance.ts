"use client";

import { useCallback, useEffect, useState } from "react";
import type { InsuranceCardData } from "@/types/chat";

const STORAGE_PREFIX = "synapse:selected-insurance";

/**
 * Persists the patient's chosen insurance plan for one browser tab's chat
 * session — mirrors widget-provider.tsx's sessionToken sessionStorage
 * pattern. Not backend-persisted: nothing downstream (the booking wizard's
 * DetailsStep only collects name/phone/email) consumes it today, so there's
 * no consumer to justify round-tripping through ChatSession.conversation_context.
 */
export function useSelectedInsurance(clinicSlug: string | null | undefined) {
  const storageKey = `${STORAGE_PREFIX}:${clinicSlug || "default"}`;
  const [selected, setSelectedState] = useState<InsuranceCardData | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const saved = sessionStorage.getItem(storageKey);
      setSelectedState(saved ? (JSON.parse(saved) as InsuranceCardData) : null);
    } catch {
      setSelectedState(null);
    }
  }, [storageKey]);

  const setSelected = useCallback(
    (plan: InsuranceCardData | null) => {
      setSelectedState(plan);
      if (typeof window === "undefined") return;
      if (plan) sessionStorage.setItem(storageKey, JSON.stringify(plan));
      else sessionStorage.removeItem(storageKey);
    },
    [storageKey]
  );

  return { selected, setSelected };
}
