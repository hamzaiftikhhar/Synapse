"use client";

import { useState } from "react";
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
  useCreatePatient,
  useDeletePatient,
  usePatients,
  useUpdatePatient,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { Patient } from "@/types/api";

const schema = z.object({
  phone: z.string().min(5),
  first_name: z.string().min(1),
  last_name: z.string().min(1),
  email: z.string().email().optional().or(z.literal("")),
});

type FormValues = z.infer<typeof schema>;

export default function PatientsPage() {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Patient | null>(null);
  const { data, isLoading } = usePatients({ search: search || undefined, limit: 100 });
  const create = useCreatePatient();
  const update = useUpdatePatient();
  const remove = useDeletePatient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { phone: "", first_name: "", last_name: "", email: "" },
  });

  function openCreate() {
    setEditing(null);
    form.reset({ phone: "", first_name: "", last_name: "", email: "" });
    setOpen(true);
  }

  function openEdit(p: Patient) {
    setEditing(p);
    form.reset({
      phone: p.phone,
      first_name: p.first_name,
      last_name: p.last_name,
      email: p.email || "",
    });
    setOpen(true);
  }

  async function onSubmit(values: FormValues) {
    const payload = {
      phone: values.phone,
      first_name: values.first_name,
      last_name: values.last_name,
      email: values.email || "",
    };
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: payload });
        toast.success("Patient updated");
      } else {
        await create.mutateAsync(payload);
        toast.success("Patient created");
      }
      setOpen(false);
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function onDelete(id: string) {
    if (!confirm("Permanently delete this patient?")) return;
    try {
      await remove.mutateAsync(id);
      toast.success("Patient deleted");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  const rows = data?.results ?? [];

  return (
    <div>
      <PageHeader
        title="Patients"
        description="Clinic patient records used for appointments and widget OTP identity."
        actions={
          <Button className="rounded-[6px]" onClick={openCreate}>
            <Plus className="size-4" /> Add patient
          </Button>
        }
      />
      <DataTableShell
        toolbar={
          <Input
            placeholder="Search patients…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-56 rounded-[6px]"
          />
        }
      >
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !rows.length ? (
          <EmptyState title="No patients" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Verified</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-medium">{p.full_name}</TableCell>
                  <TableCell>{p.phone}</TableCell>
                  <TableCell className="text-muted-foreground">{p.email || "—"}</TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="rounded-[6px]">
                      {p.is_verified ? "Yes" : "No"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button variant="ghost" size="icon-sm" onClick={() => openEdit(p)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => onDelete(p.id)}>
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
        <DialogContent className="rounded-[6px] sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit patient" : "Add patient"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>First name</Label>
                <Input {...form.register("first_name")} className="rounded-[6px]" />
              </div>
              <div className="space-y-1.5">
                <Label>Last name</Label>
                <Input {...form.register("last_name")} className="rounded-[6px]" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Phone</Label>
              <Input {...form.register("phone")} className="rounded-[6px]" placeholder="+12125550999" />
            </div>
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input {...form.register("email")} className="rounded-[6px]" />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" className="rounded-[6px]" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" className="rounded-[6px]">Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
