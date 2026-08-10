"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/providers/auth-provider";
import { getApiErrorMessage } from "@/lib/api/client";
import { platformService } from "@/services";

type PlatformClinic = {
  id: string;
  slug: string;
  name: string;
  email: string;
  status: string;
  timezone: string;
  doctor_count: number;
  staff_count: number;
  document_count: number;
  appointment_count_30d: number;
  token_usage_30d: number;
  created_at: string;
};

export default function PlatformClinicsPage() {
  const { user, clinic, tenant, enterClinic, exitClinic, canExitClinic } =
    useAuth();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<PlatformClinic[]>([]);
  const [loading, setLoading] = useState(true);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const activeSlug = tenant || clinic?.slug || null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await platformService.listClinics(search.trim());
      setRows(data);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    if (user && user.role !== "SUPER_ADMIN") {
      router.replace("/dashboard");
      return;
    }
    void load();
  }, [user, router, load]);

  async function enter(slug: string) {
    setBusySlug(slug);
    try {
      await enterClinic(slug);
      toast.success(`Entered ${slug}`);
      router.push("/dashboard");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusySlug(null);
    }
  }

  async function exit(slug: string) {
    setBusySlug(slug);
    try {
      await exitClinic();
      toast.success("Exited clinic");
      void load();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusySlug(null);
    }
  }

  async function setStatus(id: string, status: string) {
    try {
      await platformService.patchClinic(id, { status });
      toast.success(`Status → ${status}`);
      void load();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (user && user.role !== "SUPER_ADMIN") return null;

  return (
    <div>
      <PageHeader
        title="Clinics"
        description="Create, suspend, and enter any clinic. Entering opens the clinic portal; your role stays Super Admin."
      />
      {canExitClinic && activeSlug ? (
        <div className="mb-4 rounded-xl border border-warning/25 bg-warning/10 px-3 py-2 text-sm text-foreground">
          Currently viewing{" "}
          <span className="font-semibold">{clinic?.name ?? activeSlug}</span>.
          Use Exit on that row, or Enter another clinic to switch.
        </div>
      ) : null}
      <div className="mb-4 flex gap-2">
        <Input
          placeholder="Search clinics…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Button
          type="button"
          variant="outline"
          onClick={() => void load()}
        >
          Search
        </Button>
      </div>
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading clinics…</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border bg-card">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-border bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Clinic</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Doctors</th>
                <th className="px-3 py-2 font-medium">Staff</th>
                <th className="px-3 py-2 font-medium">Appts 30d</th>
                <th className="px-3 py-2 font-medium">Tokens 30d</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const isActive = activeSlug === c.slug;
                return (
                  <tr
                    key={c.id}
                    className={
                      isActive
                        ? "border-b border-border bg-warning/10 last:border-0"
                        : "border-b border-border last:border-0"
                    }
                  >
                    <td className="px-3 py-2.5">
                      <p className="font-medium">
                        {c.name}
                        {isActive ? (
                          <span className="ml-2 rounded bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-warning">
                            Viewing
                          </span>
                        ) : null}
                      </p>
                      <p className="text-xs text-muted-foreground">{c.slug}</p>
                    </td>
                    <td className="px-3 py-2.5 capitalize">{c.status}</td>
                    <td className="px-3 py-2.5">{c.doctor_count}</td>
                    <td className="px-3 py-2.5">{c.staff_count}</td>
                    <td className="px-3 py-2.5">{c.appointment_count_30d}</td>
                    <td className="px-3 py-2.5">{c.token_usage_30d}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        {isActive ? (
                          <Button
                            size="sm"
                            variant="outline"                            disabled={busySlug === c.slug}
                            onClick={() => void exit(c.slug)}
                          >
                            {busySlug === c.slug ? "…" : "Exit"}
                          </Button>
                        ) : (
                          <Button
                            size="sm"                            disabled={busySlug === c.slug}
                            onClick={() => void enter(c.slug)}
                          >
                            {busySlug === c.slug ? "…" : "Enter"}
                          </Button>
                        )}
                        {c.status !== "suspended" ? (
                          <Button
                            size="sm"
                            variant="outline"                            onClick={() => void setStatus(c.id, "suspended")}
                          >
                            Suspend
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"                            onClick={() => void setStatus(c.id, "active")}
                          >
                            Activate
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No clinics found.</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
