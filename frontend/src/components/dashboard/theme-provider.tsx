"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

type Theme = "dark" | "light";

const STORAGE_KEY = "synapse-dashboard-theme";

const ThemeContext = createContext<{ theme: Theme; toggle: () => void } | null>(
  null
);

/**
 * Scopes the Instrument design language to the dashboard subtree only —
 * marketing, auth, and onboarding keep their existing look untouched.
 * Dark is the product default; light is opt-in and persisted locally.
 */
export function DashboardThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") setTheme(stored);
  }, []);

  // Dialogs, dropdowns, selects, and tooltips portal to document.body, which
  // sits outside this wrapper's DOM subtree — mirror the scope class there
  // too, for the lifetime of the dashboard, so portaled content themes
  // correctly. Removed on unmount so marketing/auth/onboarding are untouched.
  useEffect(() => {
    document.body.classList.add("theme-instrument");
    return () => {
      document.body.classList.remove("theme-instrument", "theme-light");
    };
  }, []);

  useEffect(() => {
    document.body.classList.toggle("theme-light", theme === "light");
  }, [theme]);

  function toggle() {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      window.localStorage.setItem(STORAGE_KEY, next);
      return next;
    });
  }

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      <div
        className={cn(
          "theme-instrument min-h-screen",
          theme === "light" && "theme-light"
        )}
      >
        {children}
      </div>
    </ThemeContext.Provider>
  );
}

export function useDashboardTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useDashboardTheme must be used within DashboardThemeProvider");
  }
  return ctx;
}
