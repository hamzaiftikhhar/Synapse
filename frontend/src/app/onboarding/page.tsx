"use client";

import Link from "next/link";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { useAuth } from "@/providers/auth-provider";

const STEPS = [
  { title: "Clinic profile", href: "/dashboard/clinic" },
  { title: "Doctors & specialties", href: "/dashboard/doctors" },
  { title: "Services", href: "/dashboard/services" },
  { title: "Knowledge base", href: "/dashboard/knowledge" },
  { title: "Widget & booking", href: "/dashboard/settings" },
];

function OnboardingInner() {
  const { clinic } = useAuth();

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-2xl font-semibold tracking-tight">
        Welcome{clinic?.name ? ` to ${clinic.name}` : ""}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Finish these steps to go live. You can skip and complete them later from
        Settings.
      </p>
      <ol className="mt-8 space-y-3">
        {STEPS.map((step, i) => (
          <li
            key={step.href}
            className="flex items-center justify-between rounded-[6px] border border-border bg-white px-4 py-3"
          >
            <p className="text-sm font-medium">
              {i + 1}. {step.title}
            </p>
            <Link
              href={step.href}
              className="inline-flex h-8 items-center rounded-[6px] border border-border px-3 text-sm hover:bg-muted"
            >
              Open
            </Link>
          </li>
        ))}
      </ol>
      <div className="mt-8">
        <Link
          href="/dashboard"
          className="inline-flex h-8 items-center rounded-[6px] bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Go to dashboard
        </Link>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <ProtectedRoute>
      <OnboardingInner />
    </ProtectedRoute>
  );
}
