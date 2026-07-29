"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { useAuth } from "@/providers/auth-provider";
import { getApiErrorMessage } from "@/lib/api/client";
import { APP_NAME } from "@/constants";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
  clinic_slug: z.string().min(1, "Clinic slug is required"),
  remember: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const search = useSearchParams();
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: "",
      password: "",
      clinic_slug: "acme-cardiology",
      remember: true,
    },
  });

  async function onSubmit(values: FormValues) {
    setSubmitting(true);
    try {
      await login(
        {
          email: values.email,
          password: values.password,
          clinic_slug: values.clinic_slug,
        },
        values.remember
      );
      toast.success("Welcome back");
      const next = search.get("next") || "/dashboard";
      router.replace(next);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-[400px]">
      <div className="mb-8">
        <Link href="/" className="text-lg font-semibold tracking-tight text-navy">
          {APP_NAME}
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight text-navy">
          Sign in to your clinic
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Manage doctors, services, knowledge, and your patient chatbot.
        </p>
      </div>

      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="clinic_slug">Clinic slug</Label>
          <Input
            id="clinic_slug"
            placeholder="acme-cardiology"
            autoComplete="organization"
            {...form.register("clinic_slug")}
          />
          {form.formState.errors.clinic_slug && (
            <p className="text-xs text-destructive">
              {form.formState.errors.clinic_slug.message}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            placeholder="you@clinic.com"
            autoComplete="email"
            {...form.register("email")}
          />
          {form.formState.errors.email && (
            <p className="text-xs text-destructive">
              {form.formState.errors.email.message}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link
              href="/forgot-password"
              className="text-xs text-primary hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            {...form.register("password")}
          />
          {form.formState.errors.password && (
            <p className="text-xs text-destructive">
              {form.formState.errors.password.message}
            </p>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <Checkbox
            checked={form.watch("remember")}
            onCheckedChange={(v) => form.setValue("remember", Boolean(v))}
          />
          Remember me on this device
        </label>
        <Button type="submit" className="w-full rounded-[6px]" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-muted-foreground">
        Need an account?{" "}
        <Link href="/register" className="text-primary hover:underline">
          Request access
        </Link>
      </p>
    </div>
  );
}
