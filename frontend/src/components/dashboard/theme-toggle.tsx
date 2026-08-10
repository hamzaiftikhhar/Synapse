"use client";

import { Moon, Sun } from "lucide-react";
import { useDashboardTheme } from "@/components/dashboard/theme-provider";

export function ThemeToggle() {
  const { theme, toggle } = useDashboardTheme();
  const isLight = theme === "light";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={isLight}
      aria-label={isLight ? "Switch to dark theme" : "Switch to light theme"}
      className="inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {isLight ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}
