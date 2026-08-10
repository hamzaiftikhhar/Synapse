"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateWidgetSettings, useWidgetSettings } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "general", label: "General" },
  { id: "booking", label: "Booking & verification" },
  { id: "widget", label: "Widget" },
  { id: "features", label: "Feature flags" },
  { id: "security", label: "Security" },
  { id: "notifications", label: "Notifications" },
] as const;

function BookingSection() {
  const { data, isLoading } = useWidgetSettings();
  const update = useUpdateWidgetSettings();
  const [leadTime, setLeadTime] = useState("24");
  const [policy, setPolicy] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!data || loaded) return;
    setLeadTime(String(data.configuration.booking?.lead_time_hours ?? 24));
    setPolicy(data.configuration.booking?.cancellation_policy ?? "");
    setLoaded(true);
  }, [data, loaded]);

  async function onSave() {
    try {
      await update.mutateAsync({
        configuration: {
          booking: {
            lead_time_hours: Math.max(0, parseInt(leadTime, 10) || 0),
            cancellation_policy: policy.trim(),
          },
        },
      });
      toast.success("Booking settings saved");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading && !loaded) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-4">
      <h2 className="text-sm font-semibold">Booking & verification</h2>
      <p className="text-sm text-muted-foreground">
        Patient verification mode is{" "}
        <code className="rounded bg-muted px-1">
          {data?.configuration.booking?.verification_mode ?? "sms"}
        </code>
        . Change it from Chatbot settings.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Booking lead time (hours)</Label>
          <Input
            type="number"
            min={0}
            value={leadTime}
            onChange={(e) => setLeadTime(e.target.value)}
            className="w-32"
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label>Cancellation policy</Label>
        <Textarea rows={3} value={policy} onChange={(e) => setPolicy(e.target.value)} />
      </div>
      <Button onClick={onSave} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}

function WidgetSection() {
  const { data, isLoading } = useWidgetSettings();
  const update = useUpdateWidgetSettings();
  const [color, setColor] = useState("#5b21b6");
  const [greeting, setGreeting] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!data || loaded) return;
    setColor(data.configuration.widget?.primary_color ?? "#5b21b6");
    setGreeting(data.configuration.widget?.greeting ?? "");
    setLoaded(true);
  }, [data, loaded]);

  async function onSave() {
    try {
      await update.mutateAsync({
        configuration: { widget: { primary_color: color, greeting: greeting.trim() } },
      });
      toast.success("Widget settings saved");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading && !loaded) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-4">
      <h2 className="text-sm font-semibold">Widget</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Brand color</Label>
          <div className="flex items-center gap-2">
            <span
              className="size-8 shrink-0 rounded-full border border-border"
              style={{ backgroundColor: color }}
            />
            <Input value={color} onChange={(e) => setColor(e.target.value)} className="w-28" />
          </div>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label>Greeting</Label>
        <Input value={greeting} onChange={(e) => setGreeting(e.target.value)} />
      </div>
      <Button onClick={onSave} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}

export default function SettingsPage() {
  const [section, setSection] = useState<(typeof SECTIONS)[number]["id"]>(
    "general"
  );

  return (
    <div>
      <PageHeader title="Settings" description="Workspace and booking preferences." />
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
        <div className="min-w-0 flex-1 rounded-2xl border border-border bg-card p-5">
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
          {section === "booking" ? <BookingSection /> : null}
          {section === "widget" ? <WidgetSection /> : null}
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
