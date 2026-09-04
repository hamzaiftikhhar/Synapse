"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
import { BreakdownBarCard } from "@/components/dashboard/charts";
import { ImportTriggerButton } from "@/features/importer/import-trigger-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CARE_CATEGORIES } from "@/constants";
import {
  useCreateSpecialty,
  useDeleteSpecialty,
  useSpecialties,
  useUpdateSpecialty,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { Specialty } from "@/types/api";

const NO_CATEGORY = "none";

type FormState = {
  name: string;
  description: string;
  category: string;
  is_active: boolean;
};

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  category: "",
  is_active: true,
};

export default function SpecialtiesPage() {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Specialty | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [nameError, setNameError] = useState("");

  const { data, isLoading } = useSpecialties({ search: search || undefined, limit: 100 });
  const create = useCreateSpecialty();
  const update = useUpdateSpecialty();
  const remove = useDeleteSpecialty();

  const rows = data?.results ?? [];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setNameError("");
    setOpen(true);
  }

  function openEdit(s: Specialty) {
    setEditing(s);
    setForm({
      name: s.name,
      description: s.description,
      category: s.category,
      is_active: s.is_active,
    });
    setNameError("");
    setOpen(true);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setNameError("Please enter the specialty name.");
      return;
    }
    setNameError("");
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: form });
        toast.success("Specialty updated");
      } else {
        await create.mutateAsync(form);
        toast.success("Specialty added");
      }
      setOpen(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  async function onDelete(id: string) {
    if (!confirm("Remove this specialty?")) return;
    try {
      await remove.mutateAsync(id);
      toast.success("Specialty removed");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHeader
        title="Specialties"
        description="Broad areas of care patients can search by — shown to doctors and the chatbot."
        actions={
          <div className="flex gap-2">
            <ImportTriggerButton recordType="specialties" />
            <Button onClick={openCreate}>
              <Plus className="size-4" /> Add specialty
            </Button>
          </div>
        }
      />
      <div className="mb-4">
        <BreakdownBarCard
          dimension="specialty"
          title="Appointments by specialty"
          description="Top specialties in the last 30 days"
          emptyTitle="No specialty mix yet"
          emptyDescription="Visits linked to a provider specialty will show here."
        />
      </div>
      <DataTableShell
        toolbar={
          <Input
            placeholder="Search specialties…"
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
            title="No specialties yet"
            description="Add the specialties your clinic covers."
            action={
              <Button onClick={openCreate}>
                <Plus className="size-4" /> Add specialty
              </Button>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.category || "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{s.is_active ? "Active" : "Inactive"}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon-sm" onClick={() => openEdit(s)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => onDelete(s.id)}>
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
            <DialogTitle>{editing ? "Edit specialty" : "Add specialty"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={onSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                aria-invalid={Boolean(nameError)}
              />
              {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
            </div>
            <div className="space-y-1.5">
              <Label>Description</Label>
              <Textarea
                rows={3}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Category</Label>
              <Select
                value={form.category || NO_CATEGORY}
                onValueChange={(next) =>
                  setForm((f) => ({ ...f, category: next && next !== NO_CATEGORY ? next : "" }))
                }
                items={[
                  { value: NO_CATEGORY, label: "No category" },
                  ...CARE_CATEGORIES.map((c) => ({ value: c, label: c })),
                ]}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="No category" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CATEGORY}>No category</SelectItem>
                  {CARE_CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Standardizes this specialty against a shared list — helps the
                chatbot match patient concerns even when your own naming
                doesn&apos;t.
              </p>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={form.is_active}
                onCheckedChange={(v) => setForm((f) => ({ ...f, is_active: Boolean(v) }))}
              />
              Active
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
