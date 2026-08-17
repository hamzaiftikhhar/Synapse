"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePlatformClinics } from "@/hooks/api";
import { platformService } from "@/services";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatWhen } from "@/features/platform/format";
import { StatusPill } from "@/features/platform/status-pill";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/api";

export default function PlatformClinicsPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const { clinic, tenant, enterClinic, exitClinic, canExitClinic } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const { data, isLoading } = usePlatformClinics(q, ready);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({
    name: "",
    slug: "",
    email: "",
    owner_email: "",
  });
  const [creating, setCreating] = useState(false);
  const activeSlug = tenant || clinic?.slug || null;

  async function reload() {
    await qc.invalidateQueries({ queryKey: queryKeys.platformClinics(q) });
  }

  async function enter(slug: string, status: string) {
    setBusySlug(slug);
    try {
      const data = await enterClinic(slug);
      toast.success(`Entered ${data.clinic?.name ?? slug}`);
      router.push(status === "onboarding" ? "/onboarding" : "/dashboard");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusySlug(null);
    }
  }

  async function exit() {
    setBusySlug(activeSlug);
    try {
      await exitClinic();
      toast.success("Back on the platform");
      await reload();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusySlug(null);
    }
  }

  async function setStatus(id: string, status: string) {
    try {
      await platformService.patchClinic(id, { status });
      toast.success(status === "suspended" ? "Clinic suspended" : "Clinic activated");
      await reload();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function createClinic() {
    setCreating(true);
    try {
      await platformService.createClinic({
        name: form.name.trim(),
        slug: form.slug.trim(),
        email: form.email.trim(),
        owner_email: form.owner_email.trim() || undefined,
      });
      toast.success("Clinic created");
      setCreateOpen(false);
      setForm({ name: "", slug: "", email: "", owner_email: "" });
      await reload();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  if (!allowed) return null;
  const rows = data ?? [];

  return (
    <div>
      <PageHeader
        title="Clinics"
        description="Enter a tenant to operate as that clinic. Suspended clinics cannot use the assistant."
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="size-3.5" />
            New clinic
          </Button>
        }
      />

      {canExitClinic && activeSlug ? (
        <p className="mb-4 rounded-xl bg-warning/10 px-3 py-2 text-sm">
          Viewing <span className="font-medium">{clinic?.name ?? activeSlug}</span>. Exit to return
          to the platform, or enter another clinic.
        </p>
      ) : null}

      <DataTableShell
        toolbar={
          <form
            className="flex w-full gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setQ(search.trim());
            }}
          >
            <Input
              placeholder="Search name or slug…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-xs"
            />
            <Button type="submit" size="sm" variant="outline">
              Search
            </Button>
          </form>
        }
      >
        {isLoading ? (
          <p className="px-5 py-8 text-sm text-muted-foreground">Loading clinics…</p>
        ) : rows.length === 0 ? (
          <EmptyState title="No clinics" description="Create one, or approve an application." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Clinic</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Doctors</TableHead>
                <TableHead className="text-right">Staff</TableHead>
                <TableHead className="text-right">Appts 30d</TableHead>
                <TableHead className="pr-5 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((c) => {
                const isActive = activeSlug === c.slug;
                return (
                  <TableRow key={c.id} className={isActive ? "bg-warning/5" : undefined}>
                    <TableCell className="pl-5">
                      <p className="font-medium text-navy">{c.name}</p>
                      <p className="text-[11px] text-muted-foreground">
                        {c.slug} · {formatWhen(c.created_at)}
                      </p>
                    </TableCell>
                    <TableCell>
                      <StatusPill value={c.status} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{c.doctor_count}</TableCell>
                    <TableCell className="text-right tabular-nums">{c.staff_count}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {c.appointment_count_30d}
                    </TableCell>
                    <TableCell className="pr-5">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        {isActive ? (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busySlug === c.slug}
                            onClick={() => void exit()}
                          >
                            Exit
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            disabled={busySlug === c.slug}
                            onClick={() => void enter(c.slug, c.status)}
                          >
                            {c.status === "onboarding" ? "Enter setup" : "Enter"}
                          </Button>
                        )}
                        {c.status !== "suspended" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void setStatus(c.id, "suspended")}
                          >
                            Suspend
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void setStatus(c.id, "active")}
                          >
                            Activate
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </DataTableShell>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New clinic</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                value={form.name}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    name: e.target.value,
                    slug: f.slug || e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
                  }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label>Slug</Label>
              <Input
                value={form.slug}
                onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Clinic email</Label>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Owner email (optional invite)</Label>
              <Input
                type="email"
                value={form.owner_email}
                onChange={(e) => setForm((f) => ({ ...f, owner_email: e.target.value }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={creating || !form.name.trim() || !form.slug.trim() || !form.email.trim()}
              onClick={() => void createClinic()}
            >
              {creating ? "Creating…" : "Create clinic"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
