"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
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

const schema = z.object({
  owner_name: z.string().min(1, "Name is required"),
  work_email: z.string().email("Enter a valid work email"),
  clinic_name: z.string().min(1, "Clinic/company name is required"),
  phone: z.string().optional(),
  notes: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

function ContactInner() {
  const isEnterprise = useSearchParams().get("interest") === "enterprise";
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { owner_name: "", work_email: "", clinic_name: "", phone: "", notes: "" },
  });

  async function onSubmit(values: FormValues) {
    setSubmitting(true);
    try {
      await applicationsService.submit({
        clinic_name: values.clinic_name,
        owner_name: values.owner_name,
        work_email: values.work_email,
        phone: values.phone || "",
        notes: values.notes || "",
        source: "demo_request",
      });
      setSubmitted(true);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-xl px-4 py-24 text-center sm:px-6">
        <h1 className="text-2xl font-semibold tracking-tight text-navy">
          Demo request received
        </h1>
        <p className="mt-3 text-muted-foreground">
          Thanks — our team will reach out shortly to schedule your demo.
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
    <div className="mx-auto max-w-xl px-4 py-20 sm:px-6">
      <h1 className="text-4xl font-semibold tracking-tight text-navy">
        {isEnterprise ? "Talk to us about Enterprise" : "Book a demo"}
      </h1>
      <p className="mt-3 text-muted-foreground">
        {isEnterprise
          ? "Tell us about your clinics and requirements — our team will follow up to scope a custom plan."
          : "Tell us about your clinic and we'll be in touch to schedule a demo."}
      </p>
      <form className="mt-8 space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
        <div className="space-y-1.5">
          <Label htmlFor="owner_name">Name</Label>
          <Input id="owner_name" className="rounded-[6px]" {...form.register("owner_name")} />
          {form.formState.errors.owner_name && (
            <p className="text-xs text-destructive">{form.formState.errors.owner_name.message}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="work_email">Work email</Label>
          <Input
            id="work_email"
            type="email"
            autoComplete="email"
            className="rounded-[6px]"
            {...form.register("work_email")}
          />
          {form.formState.errors.work_email && (
            <p className="text-xs text-destructive">{form.formState.errors.work_email.message}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="clinic_name">Clinic/company name</Label>
          <Input id="clinic_name" className="rounded-[6px]" {...form.register("clinic_name")} />
          {form.formState.errors.clinic_name && (
            <p className="text-xs text-destructive">{form.formState.errors.clinic_name.message}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="phone">Phone</Label>
          <Input id="phone" type="tel" className="rounded-[6px]" {...form.register("phone")} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="notes">Message</Label>
          <Textarea id="notes" rows={4} className="rounded-[6px]" {...form.register("notes")} />
        </div>
        <Button type="submit" className="rounded-[6px]" disabled={submitting}>
          {submitting ? "Sending…" : "Request demo"}
        </Button>
      </form>
    </div>
  );
}

export default function ContactPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-xl px-4 py-20 text-sm text-muted-foreground">Loading…</div>}>
      <ContactInner />
    </Suspense>
  );
}
