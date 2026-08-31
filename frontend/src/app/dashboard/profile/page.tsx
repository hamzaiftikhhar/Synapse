"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { WorkspaceRelated } from "@/components/dashboard/workspace-related";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/providers/auth-provider";
import { authService } from "@/services";
import { getApiErrorMessage } from "@/lib/api/client";
import { roleLabel } from "@/features/platform/format";

export default function ProfilePage() {
  const { user, clinic, refreshMe } = useAuth();
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [phone, setPhone] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [pwdBusy, setPwdBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    setFirst(user.first_name ?? "");
    setLast(user.last_name ?? "");
    setPhone(user.phone_number ?? "");
  }, [user]);

  async function saveProfile() {
    setSaving(true);
    try {
      await authService.patchMe({
        first_name: first.trim(),
        last_name: last.trim(),
        phone_number: phone.trim(),
      });
      await refreshMe();
      toast.success("Profile saved");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function savePassword() {
    if (next !== confirm) {
      toast.error("New passwords do not match");
      return;
    }
    setPwdBusy(true);
    try {
      await authService.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("Password changed");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setPwdBusy(false);
    }
  }

  const isPlatform = user?.role === "SUPER_ADMIN" && !clinic;

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Your account"
        description="This is your staff login — name, email, and password. Clinic name and address are on Clinic profile."
      />

      <div className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>First name</Label>
                <Input value={first} onChange={(e) => setFirst(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Last name</Label>
                <Input value={last} onChange={(e) => setLast(e.target.value)} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input value={user?.email ?? ""} disabled />
            </div>
            <div className="space-y-1.5">
              <Label>Phone</Label>
              <Input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            <Button disabled={saving} onClick={() => void saveProfile()}>
              {saving ? "Saving…" : "Save profile"}
            </Button>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Access</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Role</span>
              <Badge variant="secondary">{user ? roleLabel(user.role) : "—"}</Badge>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Workspace</span>
              <span className="text-right font-medium text-foreground">
                {clinic?.name ?? (user?.role === "SUPER_ADMIN" ? "Platform" : "—")}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Verified</span>
              <span className="text-foreground">
                {user?.email_verified ? "Yes" : "No"}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-5">
          <CardHeader>
            <CardTitle>Password</CardTitle>
          </CardHeader>
          <CardContent className="grid max-w-lg gap-3">
            <div className="space-y-1.5">
              <Label>Current password</Label>
              <Input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>New password</Label>
                <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label>Confirm</Label>
                <Input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </div>
            </div>
            <Button
              variant="outline"
              disabled={pwdBusy || !current || next.length < 8}
              onClick={() => void savePassword()}
            >
              {pwdBusy ? "Updating…" : "Change password"}
            </Button>
          </CardContent>
        </Card>
      </div>

      {isPlatform ? null : <WorkspaceRelated current="profile" />}
    </div>
  );
}
