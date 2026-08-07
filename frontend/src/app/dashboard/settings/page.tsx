"use client";

import { useState } from "react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "general", label: "General" },
  { id: "booking", label: "Booking & verification" },
  { id: "widget", label: "Widget" },
  { id: "features", label: "Feature flags" },
  { id: "security", label: "Security" },
  { id: "notifications", label: "Notifications" },
] as const;

export default function SettingsPage() {
  const [section, setSection] = useState<(typeof SECTIONS)[number]["id"]>(
    "general"
  );

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Workspace preferences. Persist APIs land next — structure is ready."
      />
      <div className="flex flex-col gap-6 lg:flex-row">
        <nav className="flex shrink-0 gap-1 overflow-x-auto lg:w-48 lg:flex-col">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSection(s.id)}
              className={cn(
                "rounded-xl px-3 py-2 text-left text-sm whitespace-nowrap",
                section === s.id
                  ? "bg-primary/10 font-medium text-primary"
                  : "text-muted-foreground hover:bg-muted"
              )}
            >
              {s.label}
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1 rounded-2xl border border-border bg-white p-5 shadow-soft">
          {section === "general" ? (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold">General</h2>
              <p className="text-sm text-muted-foreground">
                Clinic name, timezone, and contact details are managed under
                Clinic for now.
              </p>
              <a
                href="/dashboard/clinic"
                className="inline-flex h-8 items-center rounded-lg border border-border px-3 text-sm hover:bg-muted"
              >
                Open clinic profile
              </a>
            </div>
          ) : null}
          {section === "booking" ? (
            <div className="space-y-4">
              <h2 className="text-sm font-semibold">Booking & verification</h2>
              <p className="text-sm text-muted-foreground">
                Patient verification mode:{" "}
                <code className="rounded bg-muted px-1">sms</code> |{" "}
                <code className="rounded bg-muted px-1">email</code> |{" "}
                <code className="rounded bg-muted px-1">sms_or_email</code> |{" "}
                <code className="rounded bg-muted px-1">none</code>
              </p>
              <div className="space-y-2">
                <Label className="text-xs">Current (read-only preview)</Label>
                <p className="text-sm">sms (default from widget configuration)</p>
              </div>
            </div>
          ) : null}
          {section === "widget" ? (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold">Widget</h2>
              <p className="text-sm text-muted-foreground">
                Branding and greeting live in widget configuration. Edit via Chatbot
                or Clinic until settings PATCH ships.
              </p>
            </div>
          ) : null}
          {section === "features" ? (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold">Feature flags</h2>
              <ul className="list-inside list-disc text-sm text-muted-foreground">
                <li>ai_chat, booking, knowledge_base, analytics</li>
                <li>email_otp, sms_otp</li>
                <li>doctor_portal</li>
              </ul>
            </div>
          ) : null}
          {section === "security" ? (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold">Security</h2>
              <p className="text-sm text-muted-foreground">
                Change password from Profile. 2FA is deferred.
              </p>
              <a
                href="/dashboard/profile"
                className="inline-flex h-8 items-center rounded-lg border border-border px-3 text-sm hover:bg-muted"
              >
                Open profile
              </a>
            </div>
          ) : null}
          {section === "notifications" ? (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold">Notifications</h2>
              <p className="text-sm text-muted-foreground">
                Staff verification and password reset use NotificationService
                (console/SMTP). Patient OTP uses SMS or email providers.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
