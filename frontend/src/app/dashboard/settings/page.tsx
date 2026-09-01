"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { WorkspaceRelated } from "@/components/dashboard/workspace-related";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateWidgetSettings, useWidgetSettings } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { appearanceFromConfig, appearanceToConfig } from "@/features/chat/widget-theme";
import { WidgetAppearanceEditor } from "@/features/chat/widget-appearance-editor";
import { useAuth } from "@/providers/auth-provider";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "workspace", label: "Workspace" },
  { id: "booking", label: "Booking" },
  { id: "widget", label: "Widget" },
  { id: "notifications", label: "Notifications" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

function isSectionId(value: string | null): value is SectionId {
  return SECTIONS.some((s) => s.id === value);
}

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
      <div>
        <h2 className="text-sm font-semibold text-foreground">Booking</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Lead time and cancellation copy for the patient widget. Identity
          verification mode is{" "}
          <code className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-foreground">
            {data?.configuration.booking?.verification_mode ?? "email"}
          </code>
          — change it from Chatbot when that control ships.
        </p>
      </div>
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
  const { clinic } = useAuth();
  const { data, isLoading } = useWidgetSettings();
  const update = useUpdateWidgetSettings();
  const [greeting, setGreeting] = useState("");
  const [appearance, setAppearance] = useState(() => appearanceFromConfig());
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!data || loaded) return;
    setGreeting(data.configuration.widget?.greeting ?? "");
    setAppearance(appearanceFromConfig(data.configuration.widget));
    setLoaded(true);
  }, [data, loaded]);

  async function onSave() {
    try {
      await update.mutateAsync({
        configuration: {
          widget: {
            ...appearanceToConfig(appearance),
            greeting: greeting.trim(),
          },
        },
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
    <div className="space-y-5">
      <div>
        <h2 className="text-sm font-semibold text-foreground">Widget</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Greeting and appearance patients see on your site. Use Chatbot to
          QA the live assistant.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label>Greeting</Label>
        <Input value={greeting} onChange={(e) => setGreeting(e.target.value)} />
      </div>
      <WidgetAppearanceEditor
        value={appearance}
        onChange={setAppearance}
        clinicName={clinic?.name}
        greeting={greeting}
      />
      <Button onClick={onSave} disabled={update.isPending}>
        {update.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}

function WorkspaceSection() {
  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-foreground">Workspace</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Settings is for booking rules, the public widget, and notifications.
          Clinic identity and your staff login are separate so they are not
          edited in two places.
        </p>
      </div>
      <ul className="space-y-2 text-sm text-muted-foreground">
        <li>
          <span className="font-medium text-foreground">Clinic profile</span>
          {" — "}
          practice name, address, and clinic contact.
        </li>
        <li>
          <span className="font-medium text-foreground">Business hours</span>
          {" — "}
          weekly open and close times used for booking.
        </li>
        <li>
          <span className="font-medium text-foreground">Your account</span>
          {" — "}
          staff name, email, and password (avatar menu).
        </li>
      </ul>
    </div>
  );
}

function SettingsBody() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fromUrl = searchParams.get("tab");
  const section: SectionId = isSectionId(fromUrl) ? fromUrl : "workspace";

  function setSection(id: SectionId) {
    router.replace(`/dashboard/settings?tab=${id}`, { scroll: false });
  }

  return (
    <div className="max-w-5xl">
      <PageHeader
        title="Settings"
        description="Workspace preferences for booking, the patient widget, and notifications."
      />
      <div className="flex flex-col gap-6 lg:flex-row">
        <nav
          aria-label="Settings sections"
          className="flex shrink-0 gap-1 overflow-x-auto lg:w-48 lg:flex-col"
        >
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSection(s.id)}
              className={cn(
                "rounded-lg px-3 py-2 text-left text-sm whitespace-nowrap",
                section === s.id
                  ? "bg-primary/10 font-medium text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {s.label}
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1 rounded-xl bg-card p-5 ring-1 ring-foreground/6">
          {section === "workspace" ? <WorkspaceSection /> : null}
          {section === "booking" ? <BookingSection /> : null}
          {section === "widget" ? <WidgetSection /> : null}
          {section === "notifications" ? (
            <div className="space-y-2">
              <h2 className="text-sm font-semibold text-foreground">
                Notifications
              </h2>
              <p className="text-sm text-muted-foreground">
                Staff verification and password reset use the platform
                notification service (console or SMTP). Patient OTP uses SMS
                or email providers configured for the clinic.
              </p>
            </div>
          ) : null}
        </div>
      </div>
      <WorkspaceRelated current="settings" />
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense
      fallback={
        <p className="text-sm text-muted-foreground">Loading settings…</p>
      }
    >
      <SettingsBody />
    </Suspense>
  );
}
