"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { usePlatformClinics, usePlatformUsers, queryKeys } from "@/hooks/api";
import { platformService } from "@/services";
import { getApiErrorMessage } from "@/lib/api/client";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatWhen, roleLabel } from "@/features/platform/format";
import { useQueryClient } from "@tanstack/react-query";
import type { PlatformUser } from "@/types/api";

export default function PlatformUsersPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const qc = useQueryClient();
  const [role, setRole] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const params = { search: q || undefined, role: role || undefined };
  const { data, isLoading } = usePlatformUsers(params, ready);
  const clinics = usePlatformClinics("", ready);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [form, setForm] = useState({
    email: "",
    first_name: "",
    last_name: "",
    clinic_id: "",
    role: "STAFF",
  });
  const [busy, setBusy] = useState(false);

  async function reload() {
    await qc.invalidateQueries({ queryKey: queryKeys.platformUsers(params) });
  }

  async function invite() {
    setBusy(true);
    try {
      await platformService.inviteUser(form);
      toast.success("Invite sent");
      setInviteOpen(false);
      setForm({ email: "", first_name: "", last_name: "", clinic_id: "", role: "STAFF" });
      await reload();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(user: PlatformUser) {
    try {
      await platformService.patchUser(user.id, { is_active: !user.is_active });
      toast.success(user.is_active ? "Account deactivated" : "Account activated");
      await reload();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (!allowed) return null;
  const rows = data ?? [];

  return (
    <div>
      <PageHeader
        title="Users"
        description="Clinic owners, staff, and platform operators. Invites email a one-time setup link."
        actions={
          <Button size="sm" onClick={() => setInviteOpen(true)}>
            <Plus className="size-3.5" />
            Invite
          </Button>
        }
      />

      <DataTableShell
        toolbar={
          <div className="flex w-full flex-wrap items-center gap-2">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                setQ(search.trim());
              }}
            >
              <Input
                placeholder="Search name or email…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-56"
              />
              <Button type="submit" size="sm" variant="outline">
                Search
              </Button>
            </form>
            <Tabs value={role} onValueChange={setRole}>
              <TabsList>
                <TabsTrigger value="" className="px-3">
                  All
                </TabsTrigger>
                <TabsTrigger value="CLINIC_ADMIN" className="px-3">
                  Admins
                </TabsTrigger>
                <TabsTrigger value="STAFF" className="px-3">
                  Staff
                </TabsTrigger>
                <TabsTrigger value="SUPER_ADMIN" className="px-3">
                  Platform
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        }
      >
        {isLoading ? (
          <p className="px-5 py-8 text-sm text-muted-foreground">Loading users…</p>
        ) : rows.length === 0 ? (
          <EmptyState title="No users" description="Invite a clinic admin or staff member." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-5">Person</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Clinics</TableHead>
                <TableHead>Last login</TableHead>
                <TableHead className="pr-5 text-right">Account</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="pl-5">
                    <p className="font-medium text-navy">
                      {u.first_name || u.last_name
                        ? `${u.first_name} ${u.last_name}`.trim()
                        : u.email}
                    </p>
                    <p className="text-[11px] text-muted-foreground">{u.email}</p>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{roleLabel(u.role)}</Badge>
                  </TableCell>
                  <TableCell className="max-w-[220px] truncate text-xs text-muted-foreground">
                    {u.clinics.length
                      ? u.clinics.map((c) => c.name).join(", ")
                      : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatWhen(u.last_login)}
                  </TableCell>
                  <TableCell className="pr-5 text-right">
                    {u.role === "SUPER_ADMIN" ? (
                      <Badge variant={u.is_active ? "success" : "outline"}>
                        {u.is_active ? "Active" : "Off"}
                      </Badge>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => void toggleActive(u)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DataTableShell>

      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Invite staff</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>First name</Label>
                <Input
                  value={form.first_name}
                  onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Last name</Label>
                <Input
                  value={form.last_name}
                  onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Clinic</Label>
              <select
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                value={form.clinic_id}
                onChange={(e) => setForm((f) => ({ ...f, clinic_id: e.target.value }))}
              >
                <option value="">Select clinic</option>
                {(clinics.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>Role</Label>
              <select
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
              >
                <option value="STAFF">Staff</option>
                <option value="CLINIC_ADMIN">Clinic admin</option>
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInviteOpen(false)}>
              Cancel
            </Button>
            <Button disabled={busy || !form.email || !form.clinic_id} onClick={() => void invite()}>
              {busy ? "Sending…" : "Send invite"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
