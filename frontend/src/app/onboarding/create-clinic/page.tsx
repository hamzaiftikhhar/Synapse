"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { APP_NAME } from "@/constants";
import { getApiErrorMessage } from "@/lib/api/client";
import { authService } from "@/services";
import { useAuth } from "@/providers/auth-provider";

function CreateClinicForm() {
  const router = useRouter();
  const { refreshMe, selectTenant } = useAuth();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const clinic = await authService.createClinic({
        name: name.trim(),
        slug: slug.trim() || name.trim(),
      });
      await selectTenant(clinic.slug);
      await refreshMe();
      toast.success("Clinic created");
      router.replace("/onboarding");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-6">
      <div className="w-full max-w-md rounded-[6px] border border-border bg-white p-8 shadow-sm">
        <p className="text-lg font-semibold text-navy">{APP_NAME}</p>
        <h1 className="mt-4 text-xl font-semibold tracking-tight">
          Create your clinic
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          This becomes your tenant workspace.
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Clinic name</Label>
            <Input
              id="name"
              required
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (!slug) {
                  setSlug(
                    e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, "-")
                      .replace(/^-|-$/g, "")
                  );
                }
              }}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="slug">Slug</Label>
            <Input
              id="slug"
              required
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="acme-cardiology"
            />
          </div>
          <Button className="w-full rounded-[6px]" disabled={submitting}>
            {submitting ? "Creating…" : "Create clinic"}
          </Button>
        </form>
      </div>
    </div>
  );
}

export default function CreateClinicPage() {
  return (
    <ProtectedRoute>
      <CreateClinicForm />
    </ProtectedRoute>
  );
}
