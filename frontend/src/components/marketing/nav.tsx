"use client";

import Link from "next/link";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { APP_NAME, NAV_MARKETING } from "@/constants";
import { cn } from "@/lib/utils";

export function MarketingNav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-white/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-[6px] bg-navy text-xs font-bold text-white">
            S
          </span>
          <span className="text-sm font-semibold tracking-tight text-navy">
            {APP_NAME}
          </span>
        </Link>

        <nav className="hidden items-center gap-6 md:flex">
          {NAV_MARKETING.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-sm text-muted-foreground transition-colors hover:text-navy"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-2 md:flex">
          <Link
            href="/login"
            className="inline-flex h-8 items-center rounded-[6px] px-2.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            Sign in
          </Link>
          <Link
            href="/contact"
            className="inline-flex h-8 items-center rounded-[6px] bg-primary px-3 text-sm font-medium text-primary-foreground"
          >
            Book a Demo
          </Link>
        </div>

        <button
          type="button"
          className="rounded-[6px] p-2 md:hidden"
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle menu"
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>

      <div
        className={cn(
          "border-t border-border bg-white md:hidden",
          open ? "block" : "hidden"
        )}
      >
        <div className="space-y-1 px-4 py-3">
          {NAV_MARKETING.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className="block rounded-[6px] px-2 py-2 text-sm text-navy hover:bg-muted"
            >
              {item.label}
            </Link>
          ))}
          <div className="flex gap-2 pt-2">
            <Link
              href="/login"
              className="flex-1 rounded-[6px] border border-border py-2 text-center text-sm"
            >
              Sign in
            </Link>
            <Link
              href="/contact"
              className="flex-1 rounded-[6px] bg-primary py-2 text-center text-sm font-medium text-primary-foreground"
            >
              Book a Demo
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}
