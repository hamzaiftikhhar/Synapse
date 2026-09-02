"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Plus, X } from "lucide-react";
import { EditModeActions } from "@/components/dashboard/edit-mode-actions";
import { PageHeader } from "@/components/dashboard/page-header";
import { WorkspaceRelated } from "@/components/dashboard/workspace-related";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  useClinicProfile,
  useUpdateClinicProfile,
  useUpdateWidgetSettings,
  useWidgetSettings,
} from "@/hooks/api";
import { useEditMode } from "@/hooks/use-edit-mode";
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
  const { editing, edit, cancel, done } = useEditMode();

  useEffect(() => {
    if (!data || loaded) return;
    setLeadTime(String(data.configuration.booking?.lead_time_hours ?? 24));
    setPolicy(data.configuration.booking?.cancellation_policy ?? "");
    setLoaded(true);
  }, [data, loaded]);

  function onCancel() {
    cancel(() => {
      if (!data) return;
      setLeadTime(String(data.configuration.booking?.lead_time_hours ?? 24));
      setPolicy(data.configuration.booking?.cancellation_policy ?? "");
    });
  }

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
      done();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading && !loaded) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
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
        <EditModeActions
          editing={editing}
          pending={update.isPending}
          onEdit={edit}
          onSave={onSave}
          onCancel={onCancel}
        />
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
            disabled={!editing}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label>Cancellation policy</Label>
        <Textarea
          rows={3}
          value={policy}
          onChange={(e) => setPolicy(e.target.value)}
          disabled={!editing}
        />
      </div>
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
  const { editing, edit, cancel, done } = useEditMode();

  useEffect(() => {
    if (!data || loaded) return;
    setGreeting(data.configuration.widget?.greeting ?? "");
    setAppearance(appearanceFromConfig(data.configuration.widget));
    setLoaded(true);
  }, [data, loaded]);

  function onCancel() {
    cancel(() => {
      if (!data) return;
      setGreeting(data.configuration.widget?.greeting ?? "");
      setAppearance(appearanceFromConfig(data.configuration.widget));
    });
  }

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
      done();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading && !loaded) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Widget</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Greeting and appearance patients see on your site. Use Chatbot to
            QA the live assistant.
          </p>
        </div>
        <EditModeActions
          editing={editing}
          pending={update.isPending}
          onEdit={edit}
          onSave={onSave}
          onCancel={onCancel}
        />
      </div>
      {/* WidgetAppearanceEditor uses raw <input>/<button> internally with
          no disabled prop of its own — fieldset disables every descendant
          form control in one place rather than threading disabled through
          it and every input here individually. */}
      <fieldset disabled={!editing} className="space-y-5 disabled:opacity-60">
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
      </fieldset>
    </div>
  );
}

function AllowedOriginsSection() {
  const { data, isLoading } = useClinicProfile();
  const update = useUpdateClinicProfile();
  const [newOrigin, setNewOrigin] = useState("");

  const origins = data?.allowed_origins ?? [];

  async function addOrigin() {
    const value = newOrigin.trim();
    if (!value) return;
    try {
      await update.mutateAsync({ allowed_origins: [...origins, value] });
      setNewOrigin("");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function removeOrigin(origin: string) {
    try {
      await update.mutateAsync({ allowed_origins: origins.filter((o) => o !== origin) });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="space-y-3 border-t border-border pt-5">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Allowed origins</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Websites allowed to embed and use this widget, e.g.{" "}
          <code className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-foreground">
            https://yourclinic.com
          </code>
          . The widget will not work on any external site until at least one
          is added here.
        </p>
      </div>
      {origins.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {origins.map((origin) => (
            <span
              key={origin}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 py-1 pr-1.5 pl-3 text-sm"
            >
              {origin}
              <button
                type="button"
                aria-label={`Remove ${origin}`}
                onClick={() => void removeOrigin(origin)}
                className="flex size-5 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-sm text-warning">
          No origins registered yet — the widget is not usable on any
          external site.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Input
          value={newOrigin}
          onChange={(e) => setNewOrigin(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void addOrigin();
            }
          }}
          placeholder="https://yourclinic.com"
          className="min-w-[14rem] flex-1"
          aria-label="Origin URL"
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => void addOrigin()}
          disabled={!newOrigin.trim() || update.isPending}
        >
          <Plus className="size-4" /> Add
        </Button>
      </div>
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
          {section === "widget" ? (
            <div className="space-y-6">
              <WidgetSection />
              <AllowedOriginsSection />
            </div>
          ) : null}
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
