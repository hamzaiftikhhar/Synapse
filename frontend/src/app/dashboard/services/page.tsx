"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateService,
  useDeleteService,
  useServices,
  useUpdateService,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import type { Service } from "@/types/api";

const schema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  duration_min: z.coerce.number().min(5),
  price_dollars: z.string().optional(),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

function formatPrice(cents: number | null) {
  if (cents == null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

export default function ServicesPage() {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Service | null>(null);
  const { data, isLoading } = useServices({ search: search || undefined, limit: 100 });
  const create = useCreateService();
  const update = useUpdateService();
  const remove = useDeleteService();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      description: "",
      duration_min: 30,
      price_dollars: "",
      is_active: true,
    },
  });

  function openCreate() {
    setEditing(null);
    form.reset({ name: "", description: "", duration_min: 30, price_dollars: "", is_active: true });
    setOpen(true);
  }

  function openEdit(s: Service) {
    setEditing(s);
    form.reset({
      name: s.name,
      description: s.description,
      duration_min: s.duration_min,
      price_dollars: s.price_cents != null ? (s.price_cents / 100).toFixed(2) : "",
      is_active: s.is_active,
    });
    setOpen(true);
  }

  async function onSubmit(values: FormValues) {
    const price = values.price_dollars?.trim();
    const price_cents = price ? Math.round(parseFloat(price) * 100) : null;
    const payload = {
      name: values.name,
      description: values.description ?? "",
      duration_min: values.duration_min,
      price_cents,
      is_active: values.is_active,
    };
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, input: payload });
        toast.success("Service updated");
      } else {
        await create.mutateAsync(payload);
        toast.success("Service created");
      }
      setOpen(false);
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  async function onDelete(id: string) {
    if (!confirm("Soft-delete this service?")) return;
    try {
      await remove.mutateAsync(id);
      toast.success("Service removed");
    } catch (e) {
      toast.error(getApiErrorMessage(e));
    }
  }

  const rows = data?.results ?? [];

  return (
    <div>
      <PageHeader
        title="Services"
        description="Procedures and visit types patients can ask about or book."
        actions={
          <div className="flex gap-2">
            <ImportTriggerButton recordType="services" />
            <Button onClick={openCreate}>
              <Plus className="size-4" /> Add service
            </Button>
          </div>
        }
      />
      <div className="mb-4">
        <BreakdownBarCard
          dimension="service"
          title="Appointments by service"
          description="Top booked services in the last 30 days"
          emptyTitle="No service bookings yet"
          emptyDescription="Appointments linked to a service will rank them here."
        />
      </div>
      <DataTableShell
        toolbar={
          <Input
            placeholder="Search services…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-56"
          />
        }
      >
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">Loading…</p>
        ) : !rows.length ? (
          <EmptyState title="No services" description="Add a service to get started." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell>{s.duration_min} min</TableCell>
                  <TableCell>{formatPrice(s.price_cents)}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">
                      {s.is_active ? "Active" : "Inactive"}
                    </Badge>
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
            <DialogTitle>{editing ? "Edit service" : "Add service"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input {...form.register("name")} />
            </div>
            <div className="space-y-1.5">
              <Label>Description</Label>
              <Textarea {...form.register("description")} rows={3} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Duration (min)</Label>
                <Input type="number" {...form.register("duration_min")} />
              </div>
              <div className="space-y-1.5">
                <Label>Price (USD)</Label>
                <Input {...form.register("price_dollars")} placeholder="150.00" />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={form.watch("is_active")}
                onCheckedChange={(v) => form.setValue("is_active", Boolean(v))}
              />
              Active
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit">Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
