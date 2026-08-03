"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { useAuth } from "@/providers/auth-provider";
import { getApiErrorMessage } from "@/lib/api/client";
import { platformService } from "@/services";

type Overview = Awaited<ReturnType<typeof platformService.overview>>;

export default function PlatformOverviewPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (user && user.role !== "SUPER_ADMIN") {
      router.replace("/dashboard");
      return;
    }
    void (async () => {
      try {
        setData(await platformService.overview());
      } catch (err) {
        toast.error(getApiErrorMessage(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [user, router]);

  if (user && user.role !== "SUPER_ADMIN") return null;

  const cards = data
    ? [
        { label: "Clinics", value: data.clinic_count },
        { label: "Active", value: data.active_clinics },
        { label: "Suspended", value: data.suspended_clinics },
        { label: "Onboarding", value: data.onboarding_clinics },
        { label: "Appts (30d)", value: data.appointments_30d },
        { label: "AI tokens (30d)", value: data.tokens_30d.toLocaleString() },
        { label: "Documents", value: data.documents },
        { label: "Staff users", value: data.staff_users },
      ]
    : [];

  return (
    <div>
      <PageHeader
        title="Platform overview"
        description="Cross-tenant health for Synapse. Enter a clinic to operate inside its portal."
      />
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading metrics…</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {cards.map((c) => (
              <div
                key={c.label}
                className="rounded-[6px] border border-border bg-white px-4 py-3"
              >
                <p className="text-xs text-muted-foreground">{c.label}</p>
                <p className="mt-1 text-2xl font-semibold tracking-tight">
                  {c.value}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            <div className="rounded-[6px] border border-border bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">Top clinics by AI usage</h2>
                <Link
                  href="/dashboard/platform/clinics"
                  className="text-xs text-primary hover:underline"
                >
                  Manage clinics
                </Link>
              </div>
              <ul className="space-y-2">
                {(data?.top_clinics_by_tokens ?? []).map((c) => (
                  <li
                    key={c.slug}
                    className="flex items-center justify-between text-sm"
                  >
                    <span>
                      <span className="font-medium">{c.name}</span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        {c.slug}
                      </span>
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      {c.tokens_30d.toLocaleString()} tok
                    </span>
                  </li>
                ))}
                {!data?.top_clinics_by_tokens?.length ? (
                  <li className="text-sm text-muted-foreground">No usage yet.</li>
                ) : null}
              </ul>
            </div>
            <div className="rounded-[6px] border border-border bg-white p-4">
              <h2 className="mb-3 text-sm font-semibold">Quick actions</h2>
              <div className="flex flex-col gap-2">
                <Link
                  href="/dashboard/platform/clinics"
                  className="rounded-[6px] border border-border px-3 py-2 text-sm hover:bg-muted"
                >
                  View all clinics →
                </Link>
                <Link
                  href="/dashboard/platform/ai-usage"
                  className="rounded-[6px] border border-border px-3 py-2 text-sm hover:bg-muted"
                >
                  AI usage & costs →
                </Link>
                <Link
                  href="/dashboard/platform/audit"
                  className="rounded-[6px] border border-border px-3 py-2 text-sm hover:bg-muted"
                >
                  Audit logs →
                </Link>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
