"use client";

import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTableShell, EmptyState } from "@/components/dashboard/shell";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateDoctor,
  useDeleteDoctor,
  useDoctors,
  useUpdateDoctor,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { Doctor } from "@/types/api";

const schema = z.object({
  full_name: z.string().min(1, "Required"),
  title: z.string().optional(),
  bio: z.string().optional(),
  languages: z.string().optional(),
  is_active: z.boolean(),
  is_accepting_patients: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export default function DoctorsPage() {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Doctor | null>(null);
  const { data, isLoading } = useDoctors({ search: search || undefined, limit: 100 });
  const create = useCreateDoctor();
  const update = useUpdateDoctor();
  const remove = useDeleteDoctor();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      full_name: "",
      title: "",
      bio: "",
      languages: "",
      is_active: true,
      is_accepting_patients: true,
    },
  });

  function openCreate() {
    setEditing(null);
    form.reset({
      full_name: "",
      title: "",
      bio: "",
      languages: "",
      is_active: true,
      is_accepting_patients: true,
    });
    setOpen(true);
  }

  function openEdit(d: Doctor) {
    setEditing(d);
    form.reset({
      full_name: d.full_name,
      title: d.title,
      bio: d.bio,
      languages: d.languages?.join(", ") ?? "",
      is_active: d.is_active,
      is_accepting_patients: d.is_accepting_patients,
    });
    setOpen(true);
  }

  async function onSubmit(values: FormValues) {
    const payload = {
      full_name: values.full_name,
      title: values.title ?? "",
      bio: values.bio ?? "",
      languages: values.languages
        ? values.languages.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
      is_active: values.is_active,
      is_accepting_patients: values.is_accepting_patients,
    };
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: payload });
        toast.success("Doctor updated");
      } else {
        await create.mutateAsync(payload);
        toast.success("Doctor created");
      }
      setOpen(false);
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function onDelete(id: string) {
    if (!confirm("Soft-delete this doctor?")) return;
    try {
      await remove.mutateAsync(id);
      toast.success("Doctor removed");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  const rows = useMemo(() => data?.results ?? [], [data]);

  return (
    <div>
      <PageHeader
        title="Doctors"
        description="Manage providers available for booking and chatbot discovery."
        actions={
          <Button onClick={openCreate}>
            <Plus className="size-4" /> Add doctor
          </Button>
        }
      />
      <DataTableShell
        toolbar={
          <Input
            placeholder="Search doctors…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-56"
          />
        }
      >
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !rows.length ? (
          <EmptyState title="No doctors" description="Add your first provider." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((d) => (
                <TableRow key={d.id}>
                  <TableCell className="font-medium">{d.full_name}</TableCell>
                  <TableCell className="text-muted-foreground">{d.title || "—"}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Badge variant="secondary">
                        {d.is_active ? "Active" : "Inactive"}
                      </Badge>
                      {d.is_accepting_patients ? (
                        <Badge>Accepting</Badge>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon-sm" onClick={() => openEdit(d)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => onDelete(d.id)}>
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
            <DialogTitle>{editing ? "Edit doctor" : "Add doctor"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
            <div className="space-y-1.5">
              <Label>Full name</Label>
              <Input {...form.register("full_name")} />
            </div>
            <div className="space-y-1.5">
              <Label>Title</Label>
              <Input {...form.register("title")} placeholder="MD, Cardiologist" />
            </div>
            <div className="space-y-1.5">
              <Label>Bio</Label>
              <Textarea {...form.register("bio")} rows={3} />
            </div>
            <div className="space-y-1.5">
              <Label>Languages (comma-separated)</Label>
              <Input {...form.register("languages")} placeholder="English, Spanish" />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={form.watch("is_active")}
                onCheckedChange={(v) => form.setValue("is_active", Boolean(v))}
              />
              Active
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={form.watch("is_accepting_patients")}
                onCheckedChange={(v) => form.setValue("is_accepting_patients", Boolean(v))}
              />
              Accepting patients
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
