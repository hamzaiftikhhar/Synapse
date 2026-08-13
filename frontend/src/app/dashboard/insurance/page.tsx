"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { ImportTriggerButton } from "@/features/importer/import-trigger-button";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateInsurancePlan,
  useDeleteInsurancePlan,
  useInsurancePlans,
  useUpdateInsurancePlan,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { InsurancePlan } from "@/types/api";

type FormState = {
  provider_name: string;
  plan_name: string;
  plan_type: string;
  is_accepted: boolean;
};

const EMPTY_FORM: FormState = {
  provider_name: "",
  plan_name: "",
  plan_type: "",
  is_accepted: true,
};

export default function InsurancePage() {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<InsurancePlan | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [nameError, setNameError] = useState("");

  const { data, isLoading } = useInsurancePlans({ search: search || undefined, limit: 100 });
  const create = useCreateInsurancePlan();
  const update = useUpdateInsurancePlan();
  const remove = useDeleteInsurancePlan();

  const rows = data?.results ?? [];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setNameError("");
    setOpen(true);
  }

  function openEdit(plan: InsurancePlan) {
    setEditing(plan);
    setForm({
      provider_name: plan.provider_name,
      plan_name: plan.plan_name,
      plan_type: plan.plan_type,
      is_accepted: plan.is_accepted,
    });
    setNameError("");
    setOpen(true);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.provider_name.trim()) {
      setNameError("Please enter the insurance provider name.");
      return;
    }
    setNameError("");
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: form });
        toast.success("Insurance plan updated");
      } else {
        await create.mutateAsync(form);
        toast.success("Insurance plan added");
      }
      setOpen(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function onDelete(id: string) {
    if (!confirm("Remove this insurance plan?")) return;
    try {
      await remove.mutateAsync(id);
      toast.success("Insurance plan removed");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHeader
        title="Insurance"
        description="Accepted payers for booking and chatbot answers. A name is enough — plan and network are optional."
        actions={
          <div className="flex flex-wrap gap-2">
            <ImportTriggerButton recordType="insurance" />
            <Button onClick={openCreate}>
              <Plus className="size-4" /> Add insurance
            </Button>
          </div>
        }
      />
      <DataTableShell
        toolbar={
          <Input
            placeholder="Search insurance…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-56"
          />
        }
      >
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !rows.length ? (
          <EmptyState
            title="No insurance plans yet"
            description="Add a payer name, or import a spreadsheet. This never blocks booking."
            action={
              <Button onClick={openCreate}>
                <Plus className="size-4" /> Add insurance
              </Button>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Insurance</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Network / type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((plan) => (
                <TableRow key={plan.id}>
                  <TableCell className="font-medium">{plan.provider_name}</TableCell>
                  <TableCell className="text-muted-foreground">{plan.plan_name || "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{plan.plan_type || "—"}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{plan.is_accepted ? "Accepted" : "Not accepted"}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon-sm" onClick={() => openEdit(plan)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => onDelete(plan.id)}>
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DataTableShell>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit insurance plan" : "Add insurance plan"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={onSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <Label>Insurance name</Label>
              <Input
                value={form.provider_name}
                onChange={(e) => setForm((f) => ({ ...f, provider_name: e.target.value }))}
                placeholder="Aetna"
                aria-invalid={Boolean(nameError)}
              />
              {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>
                  Plan name <span className="font-normal text-muted-foreground">(optional)</span>
                </Label>
                <Input
                  value={form.plan_name}
                  onChange={(e) => setForm((f) => ({ ...f, plan_name: e.target.value }))}
                  placeholder="Gold"
                />
              </div>
              <div className="space-y-1.5">
                <Label>
                  Network / type <span className="font-normal text-muted-foreground">(optional)</span>
                </Label>
                <Input
                  value={form.plan_type}
                  onChange={(e) => setForm((f) => ({ ...f, plan_type: e.target.value }))}
                  placeholder="PPO"
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={form.is_accepted}
                onCheckedChange={(v) => setForm((f) => ({ ...f, is_accepted: Boolean(v) }))}
              />
              Currently accepted
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={create.isPending || update.isPending}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
