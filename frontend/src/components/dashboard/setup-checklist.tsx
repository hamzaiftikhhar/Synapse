"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useOnboardingStatus } from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";
import type { OnboardingChecklist } from "@/types/api";

const REQUIRED_ITEMS: Array<{ key: keyof OnboardingChecklist; label: string; href: string }> = [
  { key: "clinic", label: "Complete your clinic profile", href: "/dashboard/clinic" },
  { key: "location", label: "Complete your clinic location", href: "/dashboard/clinic" },
  { key: "providers", label: "Add a provider", href: "/dashboard/doctors" },
  { key: "services", label: "Add a service", href: "/dashboard/services" },
  { key: "hours", label: "Set business hours", href: "/dashboard/business-hours" },
  { key: "availability", label: "Set provider availability", href: "/dashboard/doctors" },
];

export function SetupChecklistCard() {
  const { clinic } = useAuth();
  const { data: status } = useOnboardingStatus(Boolean(clinic));
  const [dismissed, setDismissed] = useState(true);
  const storageKey = clinic ? `synapse_setup_dismissed_${clinic.id}` : null;

  useEffect(() => {
    if (!storageKey) return;
    setDismissed(localStorage.getItem(storageKey) === "1");
  }, [storageKey]);

  if (!status) return null;

  const missing = REQUIRED_ITEMS.filter((item) => !status.checklist[item.key]);
  const insuranceMissing = status.counts.insurance_plans === 0;
  const fullyReady = missing.length === 0 && !insuranceMissing;

  if (dismissed || fullyReady) return null;

  const percent = Math.round(
    ((REQUIRED_ITEMS.length - missing.length) / REQUIRED_ITEMS.length) * 100
  );
  const pendingCount = missing.length + (insuranceMissing ? 1 : 0);

  function dismiss() {
    if (storageKey) localStorage.setItem(storageKey, "1");
    setDismissed(true);
  }

  return (
    <Card className="mb-6">
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-navy">Clinic setup</p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {pendingCount} thing{pendingCount === 1 ? "" : "s"} could use attention.
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Dismiss"
            onClick={dismiss}
          >
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all"
            style={{ width: `${percent}%` }}
          />
        </div>
        <ul className="space-y-1">
          {missing.map((item) => (
            <li key={item.key}>
              <Link href={item.href} className="text-sm text-primary hover:underline">
                → {item.label}
              </Link>
            </li>
          ))}
          {insuranceMissing ? (
            <li>
              <Link
                href="/dashboard/insurance"
                className="text-sm text-primary hover:underline"
              >
                → Add accepted insurance
              </Link>
            </li>
          ) : null}
        </ul>
      </CardContent>
    </Card>
  );
}
