"use client";

import { useEffect, useState } from "react";
import { APP_NAME } from "@/constants";
import { readDashboardTheme } from "@/lib/workspace-handoff";
import { cn } from "@/lib/utils";
import "./workspace-loader.css";

type Props = {
  label?: string;
  className?: string;
  /** Force theme; otherwise reads dashboard theme from localStorage. */
  theme?: "light" | "dark";
};

/**
 * Single full-screen boot for auth restore, clinic handoff, login, and logout.
 * One visual always — never framed/bare variants (those caused visible flicker).
 */
export function WorkspaceLoader({
  label = "Preparing your workspace",
  className,
  theme: themeProp,
}: Props) {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => themeProp ?? (typeof window !== "undefined" ? readDashboardTheme() : "light")
  );

  useEffect(() => {
    if (themeProp) {
      setTheme(themeProp);
      return;
    }
    setTheme(readDashboardTheme());
  }, [themeProp]);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={label}
      data-theme={theme}
      className={cn(
        "synapse-boot relative flex min-h-screen flex-col items-center justify-center overflow-hidden",
        className
      )}
    >
      <div aria-hidden className="synapse-boot__wash pointer-events-none absolute inset-0" />

      <div className="synapse-boot__content relative z-10 flex w-full max-w-[17rem] flex-col items-center px-6">
        <div className="synapse-boot__mark-wrap relative flex size-[3.25rem] items-center justify-center">
          <span aria-hidden className="synapse-boot__ring synapse-boot__ring--outer" />
          <span aria-hidden className="synapse-boot__ring synapse-boot__ring--inner" />
          <div className="synapse-boot__glyph relative z-[1] flex size-11 items-center justify-center rounded-[0.85rem]">
            <span className="synapse-boot__letter select-none text-[1.15rem] font-semibold tracking-tight">
              S
            </span>
          </div>
        </div>

        <p className="synapse-boot__brand mt-7 text-[0.9375rem] font-semibold tracking-[-0.02em]">
          {APP_NAME}
        </p>
        <p className="synapse-boot__label mt-1.5 text-center text-[13px] leading-snug">
          {label}
        </p>

        <div
          aria-hidden
          className="synapse-boot__track mt-8 h-[2px] w-[7.5rem] overflow-hidden rounded-full"
        >
          <div className="synapse-boot__bar h-full w-1/3 rounded-full" />
        </div>
      </div>
    </div>
  );
}
