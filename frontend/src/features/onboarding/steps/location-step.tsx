"use client";

import { useMemo, useState } from "react";
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
import { useUpdateClinicProfile } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

const FALLBACK_TIMEZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Anchorage",
  "Pacific/Honolulu",
];

function supportedTimezones(): string[] {
  try {
    const values = (
      Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    ).supportedValuesOf?.("timeZone");
    return values && values.length ? values : FALLBACK_TIMEZONES;
  } catch {
    return FALLBACK_TIMEZONES;
  }
}

type FormState = {
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  phone: string;
  timezone: string;
};

export function LocationStep({ onNext }: OnboardingStepProps) {
  const { clinic } = useAuth();
  const updateProfile = useUpdateClinicProfile();
  const timezones = useMemo(supportedTimezones, []);

  const [form, setForm] = useState<FormState>({
    line1: clinic?.address?.line1 ?? "",
    line2: clinic?.address?.line2 ?? "",
    city: clinic?.address?.city ?? "",
    state: clinic?.address?.state ?? "",
    postal_code: clinic?.address?.postal_code ?? "",
    country: clinic?.address?.country ?? "US",
    phone: clinic?.phone ?? "",
    timezone: clinic?.timezone || "America/New_York",
  });
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const nextErrors: Partial<Record<keyof FormState, string>> = {};
    if (!form.line1.trim()) nextErrors.line1 = "Please enter a street address.";
    if (!form.city.trim()) nextErrors.city = "Please enter a city.";
    if (!form.state.trim()) nextErrors.state = "Please enter a state.";
    if (!form.postal_code.trim()) nextErrors.postal_code = "Please enter a ZIP/postal code.";
    if (!form.country.trim()) nextErrors.country = "Please enter a country.";
    if (!form.phone.trim()) nextErrors.phone = "Please enter a phone number.";
    if (Object.keys(nextErrors).length) {
      setErrors(nextErrors);
      return;
    }
    setErrors({});
    try {
      await updateProfile.mutateAsync({
        phone: form.phone.trim(),
        timezone: form.timezone,
        address: {
          line1: form.line1.trim(),
          line2: form.line2.trim(),
          city: form.city.trim(),
          state: form.state.trim(),
          postal_code: form.postal_code.trim(),
          country: form.country.trim(),
        },
      });
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="line1">Street address</Label>
        <Input
          id="line1"
          value={form.line1}
          onChange={(e) => set("line1", e.target.value)}
          placeholder="123 Main St, Suite 200"
          aria-invalid={Boolean(errors.line1)}
        />
        {errors.line1 ? <p className="text-xs text-destructive">{errors.line1}</p> : null}
      </div>
      <div className="space-y-2">
        <Label htmlFor="line2">
          Address line 2 <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <Input id="line2" value={form.line2} onChange={(e) => set("line2", e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="city">City</Label>
          <Input
            id="city"
            value={form.city}
            onChange={(e) => set("city", e.target.value)}
            aria-invalid={Boolean(errors.city)}
          />
          {errors.city ? <p className="text-xs text-destructive">{errors.city}</p> : null}
        </div>
        <div className="space-y-2">
          <Label htmlFor="state">State</Label>
          <Input
            id="state"
            value={form.state}
            onChange={(e) => set("state", e.target.value)}
            aria-invalid={Boolean(errors.state)}
          />
          {errors.state ? <p className="text-xs text-destructive">{errors.state}</p> : null}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="postal_code">ZIP / postal code</Label>
          <Input
            id="postal_code"
            value={form.postal_code}
            onChange={(e) => set("postal_code", e.target.value)}
            aria-invalid={Boolean(errors.postal_code)}
          />
          {errors.postal_code ? (
            <p className="text-xs text-destructive">{errors.postal_code}</p>
          ) : null}
        </div>
        <div className="space-y-2">
          <Label htmlFor="country">Country</Label>
          <Input
            id="country"
            value={form.country}
            onChange={(e) => set("country", e.target.value)}
            aria-invalid={Boolean(errors.country)}
          />
          {errors.country ? <p className="text-xs text-destructive">{errors.country}</p> : null}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="phone">Phone number</Label>
          <Input
            id="phone"
            type="tel"
            value={form.phone}
            onChange={(e) => set("phone", e.target.value)}
            placeholder="(555) 010-0100"
            aria-invalid={Boolean(errors.phone)}
          />
          {errors.phone ? <p className="text-xs text-destructive">{errors.phone}</p> : null}
        </div>
        <div className="space-y-2">
          <Label htmlFor="timezone">Time zone</Label>
          <Select value={form.timezone} onValueChange={(v) => v && set("timezone", v)}>
            <SelectTrigger id="timezone" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {timezones.map((tz) => (
                <SelectItem key={tz} value={tz}>
                  {tz.replace(/_/g, " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </form>
  );
}
