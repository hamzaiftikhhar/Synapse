"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { WidgetAppearanceEditor } from "@/features/chat/widget-appearance-editor";
import {
  appearanceFromConfig,
  appearanceToConfig,
  type WidgetAppearance,
} from "@/features/chat/widget-theme";
import {
  useUpdateWidgetSettings,
  useWidgetSettings,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import { StepHint } from "../step-hint";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

const LEAD_TIME_OPTIONS = [
  { value: "0", label: "Same day" },
  { value: "24", label: "24 hours" },
  { value: "48", label: "48 hours" },
  { value: "168", label: "1 week" },
  { value: "custom", label: "Custom" },
];

export function BookingStep({ onNext }: OnboardingStepProps) {
  const { clinic } = useAuth();
  const { data, isLoading } = useWidgetSettings();
  const update = useUpdateWidgetSettings();

  const [leadTimeChoice, setLeadTimeChoice] = useState("24");
  const [customLeadTime, setCustomLeadTime] = useState("24");
  const [policy, setPolicy] = useState("");
  const [greeting, setGreeting] = useState("");
  const [appearance, setAppearance] = useState<WidgetAppearance>(() =>
    appearanceFromConfig()
  );
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!data || hydrated) return;
    const savedLeadTime = data.configuration.booking?.lead_time_hours ?? 24;
    setLeadTimeChoice(
      LEAD_TIME_OPTIONS.some((o) => o.value === String(savedLeadTime))
        ? String(savedLeadTime)
        : "custom"
    );
    setCustomLeadTime(String(savedLeadTime));
    setPolicy(data.configuration.booking?.cancellation_policy ?? "");
    setGreeting(data.configuration.widget?.greeting ?? "");
    setAppearance(appearanceFromConfig(data.configuration.widget));
    setHydrated(true);
  }, [data, hydrated]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const leadTimeHours =
      leadTimeChoice === "custom"
        ? Math.max(0, parseInt(customLeadTime, 10) || 0)
        : parseInt(leadTimeChoice, 10);
    try {
      await update.mutateAsync({
        configuration: {
          booking: { lead_time_hours: leadTimeHours, cancellation_policy: policy.trim() },
          widget: {
            ...appearanceToConfig(appearance),
            greeting: greeting.trim(),
          },
        },
      });
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading && !hydrated) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit} className="space-y-8">
      <StepHint>Patients see these in the chat widget. You can change them later.</StepHint>
      <div className="space-y-3">
        <Label>How soon can patients book?</Label>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={leadTimeChoice} onValueChange={(v) => v && setLeadTimeChoice(v)}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LEAD_TIME_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {leadTimeChoice === "custom" ? (
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={0}
                value={customLeadTime}
                onChange={(e) => setCustomLeadTime(e.target.value)}
                className="w-24"
              />
              <span className="text-sm text-muted-foreground">hours notice</span>
            </div>
          ) : null}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="cancellation-policy">
          Cancellation policy{" "}
          <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <Textarea
          id="cancellation-policy"
          rows={3}
          value={policy}
          onChange={(e) => setPolicy(e.target.value)}
          placeholder="e.g. Please cancel at least 24 hours in advance."
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="widget-greeting">
          Greeting{" "}
          <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <Input
          id="widget-greeting"
          value={greeting}
          onChange={(e) => setGreeting(e.target.value)}
          placeholder={`Hi! How can ${clinic?.name || "we"} help you today?`}
        />
      </div>

      <div className="space-y-3">
        <Label>How the chat looks on your site</Label>
        <WidgetAppearanceEditor
          value={appearance}
          onChange={setAppearance}
          clinicName={clinic?.name}
          greeting={greeting}
        />
      </div>
    </form>
  );
}
