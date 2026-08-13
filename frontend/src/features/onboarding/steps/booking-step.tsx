"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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
import {
  useUpdateWidgetSettings,
  useWidgetSettings,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { StepHint } from "../step-hint";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

const LEAD_TIME_OPTIONS = [
  { value: "0", label: "Same day" },
  { value: "24", label: "24 hours" },
  { value: "48", label: "48 hours" },
  { value: "168", label: "1 week" },
  { value: "custom", label: "Custom" },
];

const COLOR_PRESETS = ["#5c67f2", "#0f766e", "#b45309", "#1d4ed8", "#be123c", "#1a1e26"];

export function BookingStep({ onNext }: OnboardingStepProps) {
  const { data, isLoading } = useWidgetSettings();
  const update = useUpdateWidgetSettings();

  const savedLeadTime = data?.configuration.booking?.lead_time_hours ?? 24;
  const savedColor = data?.configuration.widget?.primary_color ?? COLOR_PRESETS[0];
  const savedPolicy = data?.configuration.booking?.cancellation_policy ?? "";

  const [leadTimeChoice, setLeadTimeChoice] = useState<string>(
    LEAD_TIME_OPTIONS.some((o) => o.value === String(savedLeadTime))
      ? String(savedLeadTime)
      : "custom"
  );
  const [customLeadTime, setCustomLeadTime] = useState(String(savedLeadTime));
  const [policy, setPolicy] = useState(savedPolicy);
  const [color, setColor] = useState(savedColor);

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
          widget: { primary_color: color },
        },
      });
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit} className="space-y-8">
      <StepHint>
        Lead time and cancellation copy appear in the patient chatbot. You can
        change all of this later from Settings.
      </StepHint>
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

      <div className="space-y-3">
        <Label>
          Brand color{" "}
          <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <div className="flex flex-wrap items-center gap-2">
          {COLOR_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-label={`Use ${preset}`}
              aria-pressed={color === preset}
              onClick={() => setColor(preset)}
              className={cn(
                "size-8 rounded-full ring-2 ring-offset-2 ring-offset-background transition-shadow",
                color === preset ? "ring-foreground" : "ring-transparent"
              )}
              style={{ backgroundColor: preset }}
            />
          ))}
          <Input
            value={color}
            onChange={(e) => setColor(e.target.value)}
            className="w-28"
            aria-label="Custom brand color (hex)"
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Used for your booking widget. Defaults to Synapse&apos;s palette if left as-is.
        </p>
      </div>
    </form>
  );
}
