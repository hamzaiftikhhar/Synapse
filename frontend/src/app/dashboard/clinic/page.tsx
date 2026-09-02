"use client";

import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
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
import { EditModeActions } from "@/components/dashboard/edit-mode-actions";
import { WorkspaceRelated } from "@/components/dashboard/workspace-related";
import { CLINIC_TYPE_OPTIONS } from "@/features/onboarding/clinic-types";
import { useClinicProfile, useUpdateClinicProfile } from "@/hooks/api";
import { useEditMode } from "@/hooks/use-edit-mode";
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

function FieldGroup({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          {title}
        </h2>
        {description ? (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function formStateFrom(data: NonNullable<ReturnType<typeof useClinicProfile>["data"]>): FormState {
  return {
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
  };
}

export default function ClinicPage() {
  const { data, isLoading } = useClinicProfile();
  const update = useUpdateClinicProfile();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const { editing, edit, cancel, done } = useEditMode();

  useEffect(() => {
    if (!data) return;
    setForm(formStateFrom(data));
  }, [data?.id]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function onCancel() {
    cancel(() => data && setForm(formStateFrom(data)));
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
      done();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Clinic profile"
        description="How this practice appears to patients and staff. Hours, booking rules, and your personal login live on their own pages."
        actions={
          <EditModeActions
            editing={editing}
            pending={update.isPending}
            onEdit={edit}
            onSave={onSave}
            onCancel={onCancel}
          />
        }
      />
      <Card>
        <CardContent className="space-y-8">
          {isLoading && !data ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <>
              <FieldGroup
                title="Identity"
                description="Shown on the public widget and in the staff portal."
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>Clinic name</Label>
                    <Input
                      value={form.name}
                      onChange={(e) => set("name", e.target.value)}
                      disabled={!editing}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Clinic type</Label>
                    <Select
                      value={form.clinic_type || null}
                      onValueChange={(v) =>
                        v && set("clinic_type", v as ClinicType)
                      }
                      items={CLINIC_TYPE_OPTIONS}
                      disabled={!editing}
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
              </FieldGroup>

              <div className="h-px bg-border" />

              <FieldGroup
                title="Contact"
                description="Clinic inbox and phone — not your personal staff account."
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>Email</Label>
                    <Input
                      value={form.email}
                      onChange={(e) => set("email", e.target.value)}
                      disabled={!editing}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Phone</Label>
                    <Input
                      value={form.phone}
                      onChange={(e) => set("phone", e.target.value)}
                      disabled={!editing}
                    />
                  </div>
                </div>
              </FieldGroup>

              <div className="h-px bg-border" />

              <FieldGroup title="Address">
                <div className="space-y-1.5">
                  <Label>Street address</Label>
                  <Input
                    value={form.line1}
                    onChange={(e) => set("line1", e.target.value)}
                    disabled={!editing}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Address line 2</Label>
                  <Input
                    value={form.line2}
                    onChange={(e) => set("line2", e.target.value)}
                    disabled={!editing}
                  />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>City</Label>
                    <Input
                      value={form.city}
                      onChange={(e) => set("city", e.target.value)}
                      disabled={!editing}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>State</Label>
                    <Input
                      value={form.state}
                      onChange={(e) => set("state", e.target.value)}
                      disabled={!editing}
                    />
                  </div>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>ZIP / postal code</Label>
                    <Input
                      value={form.postal_code}
                      onChange={(e) => set("postal_code", e.target.value)}
                      disabled={!editing}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Country</Label>
                    <Input
                      value={form.country}
                      onChange={(e) => set("country", e.target.value)}
                      disabled={!editing}
                    />
                  </div>
                </div>
              </FieldGroup>
            </>
          )}
        </CardContent>
      </Card>
      <WorkspaceRelated current="clinic" />
    </div>
  );
}
