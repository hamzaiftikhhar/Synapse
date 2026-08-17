"use client";

import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePlatformSettings, queryKeys } from "@/hooks/api";
import { platformService } from "@/services";
import { getApiErrorMessage } from "@/lib/api/client";
import { useRequireSuperAdmin } from "@/features/platform/use-require-super-admin";
import { formatCents } from "@/features/platform/format";
import { useQueryClient } from "@tanstack/react-query";
import type { PlatformPlan } from "@/types/api";

export default function PlatformSettingsPage() {
  const { allowed, ready } = useRequireSuperAdmin();
  const qc = useQueryClient();
  const { data, isLoading } = usePlatformSettings(ready);
  const [editing, setEditing] = useState<PlatformPlan | null>(null);
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [active, setActive] = useState(true);
  const [sandboxId, setSandboxId] = useState("");
  const [liveId, setLiveId] = useState("");
  const [saving, setSaving] = useState(false);

  function openPlan(plan: PlatformPlan) {
    setEditing(plan);
    setName(plan.name);
    setPrice(plan.display_price_cents != null ? String(plan.display_price_cents / 100) : "");
    setActive(plan.is_active);
    setSandboxId(plan.paddle_price_id_sandbox);
    setLiveId(plan.paddle_price_id_live);
  }

  async function savePlan() {
    if (!editing) return;
    setSaving(true);
    try {
      const dollars = parseFloat(price);
      await platformService.patchPlan(editing.id, {
        name: name.trim(),
        display_price_cents: Number.isFinite(dollars) ? Math.round(dollars * 100) : undefined,
        is_active: active,
        paddle_price_id_sandbox: sandboxId.trim(),
        paddle_price_id_live: liveId.trim(),
      });
      toast.success("Plan updated");
      setEditing(null);
      await qc.invalidateQueries({ queryKey: queryKeys.platformSettings });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  if (!allowed) return null;

  return (
    <div>
      <PageHeader
        title="Platform settings"
        description="Integration health and the catalog clinics pick at signup. Secrets stay in the server environment."
      />

      {isLoading || !data ? (
        <p className="text-sm text-muted-foreground">Loading settings…</p>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.integrations.map((row) => (
              <Card key={row.key}>
                <CardContent className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-navy">{row.label}</p>
                    <Badge variant={row.configured ? "success" : "warning"}>
                      {row.configured ? "Connected" : "Not set"}
                    </Badge>
                  </div>
                  <p className="mt-2 truncate text-[12px] text-muted-foreground">{row.detail}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Runtime</CardTitle>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Read from the server process — change these in environment config.
              </p>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 text-sm">
              <Row label="App URL" value={data.frontend_url} />
              <Row label="Paddle" value={data.paddle_environment} />
              <Row label="NLU" value={`${data.nlu_provider} · ${data.nlu_model}`} />
              <Row
                label="Embeddings"
                value={`${data.embedding_provider} · ${data.embedding_model}`}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Plans</CardTitle>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Display price is what owners see. Paddle still bills the mapped price ID.
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.plans.map((plan) => (
                <div
                  key={plan.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-medium text-navy">{plan.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {plan.slug} · {plan.billing_interval} · {plan.subscriber_count} clinics
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm tabular-nums">
                      {formatCents(plan.display_price_cents, plan.display_currency)}
                    </span>
                    <Badge variant={plan.is_active ? "success" : "outline"}>
                      {plan.is_active ? "Live" : "Hidden"}
                    </Badge>
                    <Button size="sm" variant="outline" onClick={() => openPlan(plan)}>
                      Edit
                    </Button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit {editing?.slug}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Display price (USD)</Label>
              <Input value={price} onChange={(e) => setPrice(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Paddle sandbox price ID</Label>
              <Input value={sandboxId} onChange={(e) => setSandboxId(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>Paddle live price ID</Label>
              <Input value={liveId} onChange={(e) => setLiveId(e.target.value)} />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={active} onCheckedChange={(v) => setActive(Boolean(v))} />
              Visible on pricing
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button disabled={saving || !name.trim()} onClick={() => void savePlan()}>
              {saving ? "Saving…" : "Save plan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border py-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-medium text-navy">{value || "—"}</span>
    </div>
  );
}
