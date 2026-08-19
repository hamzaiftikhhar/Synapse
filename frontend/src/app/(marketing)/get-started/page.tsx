"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/client";
import { applicationsService } from "@/services";

const PLAN_LABELS: Record<string, { name: string; price: string }> = {
  starter: { name: "Starter", price: "$29 / month" },
  growth: { name: "Professional", price: "$49 / month" },
  professional: { name: "Professional", price: "$49 / month" },
  enterprise: { name: "Enterprise", price: "$99 / month" },
};

const schema = z.object({
  clinic_name: z.string().min(1, "Clinic name is required"),
  owner_name: z.string().min(1, "Your name is required"),
  work_email: z.string().email("Enter a valid work email"),
  phone: z.string().optional(),
  website: z.string().optional(),
  num_doctors: z.string().optional(),
  current_scheduling_system: z.string().optional(),
  notes: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

export default function GetStartedPage() {
  const searchParams = useSearchParams();
  const planSlug = searchParams.get("plan") || "";
  const plan = PLAN_LABELS[planSlug];
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      clinic_name: "", owner_name: "", work_email: "", phone: "",
      website: "", num_doctors: "", current_scheduling_system: "", notes: "",
    },
  });

  async function onSubmit(values: FormValues) {
    if (!plan) {
      toast.error("Choose a plan first");
      return;
    }
    setSubmitting(true);
    try {
      await applicationsService.submit({
        clinic_name: values.clinic_name,
        owner_name: values.owner_name,
        work_email: values.work_email,
        phone: values.phone || "",
        website: values.website || "",
        num_doctors: values.num_doctors ? Number(values.num_doctors) : null,
        current_scheduling_system: values.current_scheduling_system || "",
        plan_slug: planSlug === "professional" ? "growth" : planSlug,
        notes: values.notes || "",
        source: "get_started",
      });
      setSubmitted(true);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (!plan) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-navy">
          Choose a plan to get started
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Pick Starter or Growth on the pricing page, then come back here.
        </p>
        <Link
          href="/pricing"
          className="mt-6 inline-flex h-9 items-center justify-center rounded-[6px] bg-navy px-4 text-sm font-medium text-white"
        >
          View pricing
        </Link>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-navy">
          Application submitted
        </h1>
        <p className="mt-3 text-muted-foreground">
          Thanks — your clinic application has been received.
        </p>
        <p className="mt-1 text-muted-foreground">
          Our team will review your details and prepare your workspace. We&apos;ll
          be in touch by email shortly.
        </p>
        <Link
          href="/"
          className="mt-8 inline-flex h-9 items-center justify-center rounded-[6px] border border-border px-4 text-sm font-medium text-navy hover:bg-muted/50"
        >
          Back to home
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl px-4 py-16 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight text-navy">
        Let&apos;s get your clinic started
      </h1>
      <p className="mt-2 text-muted-foreground">
        Tell us a little about your clinic and our team will prepare your
        Synapse workspace.
      </p>

      <div className="mt-6 flex items-center justify-between rounded-[6px] border border-primary/30 bg-primary/[0.03] px-4 py-3">
        <div>
          <p className="text-xs text-muted-foreground">You&apos;re getting started with</p>
          <p className="text-sm font-semibold text-navy">
            {plan.name} <span className="font-normal text-muted-foreground">· {plan.price}</span>
          </p>
        </div>
        <Link href="/pricing" className="text-xs text-primary hover:underline">
          Change plan
        </Link>
      </div>

      <form onSubmit={form.handleSubmit(onSubmit)} className="mt-8 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="clinic_name">Clinic name</Label>
            <Input id="clinic_name" {...form.register("clinic_name")} />
            {form.formState.errors.clinic_name && (
              <p className="text-xs text-destructive">
                {form.formState.errors.clinic_name.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="owner_name">Your name</Label>
            <Input id="owner_name" {...form.register("owner_name")} />
            {form.formState.errors.owner_name && (
              <p className="text-xs text-destructive">
                {form.formState.errors.owner_name.message}
              </p>
            )}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="work_email">Work email</Label>
            <Input id="work_email" type="email" autoComplete="email" {...form.register("work_email")} />
            {form.formState.errors.work_email && (
              <p className="text-xs text-destructive">
                {form.formState.errors.work_email.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="phone">Phone</Label>
            <Input id="phone" type="tel" {...form.register("phone")} />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="website">Clinic website</Label>
            <Input id="website" placeholder="https://" {...form.register("website")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="num_doctors">Number of doctors</Label>
            <Input id="num_doctors" type="number" min={1} {...form.register("num_doctors")} />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="current_scheduling_system">Current scheduling system</Label>
          <Input
            id="current_scheduling_system"
            placeholder="e.g. spreadsheets, phone calls, another platform"
            {...form.register("current_scheduling_system")}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="notes">Anything else we should know?</Label>
          <Textarea id="notes" rows={3} {...form.register("notes")} />
        </div>
        <Button type="submit" className="w-full rounded-[6px]" disabled={submitting}>
          {submitting ? "Submitting…" : "Submit application"}
        </Button>
      </form>
    </div>
  );
}
