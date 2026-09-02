"use client";

import { useState } from "react";
import { toast } from "sonner";
import { EditModeActions } from "@/components/dashboard/edit-mode-actions";
import { PageHeader } from "@/components/dashboard/page-header";
import { WorkspaceRelated } from "@/components/dashboard/workspace-related";
import { Card, CardContent } from "@/components/ui/card";
import {
  businessHoursToWeekly,
  validateWeeklySchedule,
  weeklyToBusinessHours,
  WeeklyScheduleEditor,
  type WeeklyDayValue,
} from "@/components/dashboard/weekly-schedule-editor";
import { useBusinessHours, useUpdateBusinessHours } from "@/hooks/api";
import { useEditMode } from "@/hooks/use-edit-mode";
import { getApiErrorMessage } from "@/lib/api/client";

export default function BusinessHoursPage() {
  const { data, isLoading } = useBusinessHours();
  const update = useUpdateBusinessHours();
  const [rows, setRows] = useState<WeeklyDayValue[] | null>(null);
  const { editing, edit, cancel, done } = useEditMode();

  const value = rows ?? businessHoursToWeekly(data);

  function onCancel() {
    cancel(() => setRows(null));
  }

  async function onSave() {
    const error = validateWeeklySchedule(value);
    if (error) {
      toast.error(error);
      return;
    }
    try {
      await update.mutateAsync(weeklyToBusinessHours(value));
      toast.success("Business hours saved");
      done();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHeader
        title="Business hours"
        description="Weekly open and close times for this clinic. Used as the default for booking availability."
        actions={
          <EditModeActions
            editing={editing}
            pending={update.isPending}
            onEdit={edit}
            onSave={onSave}
            onCancel={onCancel}
          />
        }
      />
      <Card>
        <CardContent>
          {isLoading && !rows ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <WeeklyScheduleEditor value={value} onChange={setRows} disabled={!editing} />
          )}
        </CardContent>
      </Card>
      <WorkspaceRelated current="hours" />
    </div>
  );
}
