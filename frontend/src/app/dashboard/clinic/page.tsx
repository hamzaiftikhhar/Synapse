"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CLINIC_TYPE_OPTIONS } from "@/features/onboarding/clinic-types";
import { useClinicProfile, useUpdateClinicProfile } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { ClinicType } from "@/types/api";

type FormState = {
  name: string;
  clinic_type: ClinicType | "";
  email: string;
  phone: string;
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
};

const EMPTY_FORM: FormState = {
  name: "",
  clinic_type: "",
  email: "",
  phone: "",
  line1: "",
  line2: "",
  city: "",
  state: "",
  postal_code: "",
  country: "",
};

export default function ClinicPage() {
  const { data, isLoading } = useClinicProfile();
  const update = useUpdateClinicProfile();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!data || loaded) return;
    setForm({
      name: data.name,
      clinic_type: data.clinic_type ?? "",
      email: data.email,
      phone: data.phone ?? "",
      line1: data.address?.line1 ?? "",
      line2: data.address?.line2 ?? "",
      city: data.address?.city ?? "",
      state: data.address?.state ?? "",
      postal_code: data.address?.postal_code ?? "",
      country: data.address?.country ?? "",
    });
    setLoaded(true);
  }, [data, loaded]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function onSave() {
    if (!form.name.trim()) {
      toast.error("Please enter the clinic name.");
      return;
    }
    try {
      await update.mutateAsync({
        name: form.name.trim(),
        clinic_type: form.clinic_type || undefined,
        email: form.email.trim(),
        phone: form.phone.trim(),
        address: {
          line1: form.line1.trim(),
          line2: form.line2.trim(),
          city: form.city.trim(),
          state: form.state.trim(),
          postal_code: form.postal_code.trim(),
          country: form.country.trim(),
        },
      });
      toast.success("Clinic profile saved");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHeader
        title="Clinic"
        description="Clinic profile, address, and contact details."
        actions={
          <Button onClick={onSave} disabled={update.isPending}>
            {update.isPending ? "Saving…" : "Save"}
          </Button>
        }
      />
      <Card>
        <CardContent className="space-y-5">
          {isLoading && !loaded ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>Clinic name</Label>
                  <Input value={form.name} onChange={(e) => set("name", e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>Clinic type</Label>
                  <Select
                    value={form.clinic_type || undefined}
                    onValueChange={(v) => v && set("clinic_type", v as ClinicType)}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select a type" />
                    </SelectTrigger>
                    <SelectContent>
                      {CLINIC_TYPE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>Email</Label>
                  <Input value={form.email} onChange={(e) => set("email", e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>Phone</Label>
                  <Input value={form.phone} onChange={(e) => set("phone", e.target.value)} />
                </div>
              </div>
              <div className="h-px bg-border" />
              <div className="space-y-1.5">
                <Label>Street address</Label>
                <Input value={form.line1} onChange={(e) => set("line1", e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Address line 2</Label>
                <Input value={form.line2} onChange={(e) => set("line2", e.target.value)} />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>City</Label>
                  <Input value={form.city} onChange={(e) => set("city", e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>State</Label>
                  <Input value={form.state} onChange={(e) => set("state", e.target.value)} />
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>ZIP / postal code</Label>
                  <Input
                    value={form.postal_code}
                    onChange={(e) => set("postal_code", e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Country</Label>
                  <Input value={form.country} onChange={(e) => set("country", e.target.value)} />
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
