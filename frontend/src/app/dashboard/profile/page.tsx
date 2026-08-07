"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/providers/auth-provider";

export default function ProfilePage() {
  const { user, clinic } = useAuth();
  return (
    <div>
      <PageHeader
        title="Profile"
        description="Your staff account details from /auth/me."
      />
      <Card className="max-w-lg">
        <CardContent className="space-y-3 p-5 text-sm">
          <div className="flex justify-between gap-4 border-b border-border py-2">
            <span className="text-muted-foreground">Name</span>
            <span className="font-medium">
              {user?.first_name} {user?.last_name}
            </span>
          </div>
          <div className="flex justify-between gap-4 border-b border-border py-2">
            <span className="text-muted-foreground">Email</span>
            <span className="font-medium">{user?.email}</span>
          </div>
          <div className="flex justify-between gap-4 border-b border-border py-2">
            <span className="text-muted-foreground">Role</span>
            <span className="font-medium">{user?.role}</span>
          </div>
          <div className="flex justify-between gap-4 py-2">
            <span className="text-muted-foreground">Clinic</span>
            <span className="font-medium">{clinic?.name ?? "—"}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
