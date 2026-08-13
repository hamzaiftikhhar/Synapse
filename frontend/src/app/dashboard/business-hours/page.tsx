"use client";

import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  businessHoursToWeekly,
  validateWeeklySchedule,
  weeklyToBusinessHours,
  WeeklyScheduleEditor,
  type WeeklyDayValue,
} from "@/components/dashboard/weekly-schedule-editor";
import { useBusinessHours, useUpdateBusinessHours } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";

export default function BusinessHoursPage() {
  const { data, isLoading } = useBusinessHours();
  const update = useUpdateBusinessHours();
  const [rows, setRows] = useState<WeeklyDayValue[] | null>(null);

  const value = rows ?? businessHoursToWeekly(data);

  async function onSave() {
    const error = validateWeeklySchedule(value);
    if (error) {
      toast.error(error);
      return;
    }
    try {
      await update.mutateAsync(weeklyToBusinessHours(value));
      toast.success("Business hours saved");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div>
      <PageHeader
        title="Business Hours"
        description="Weekly open/close schedule for the clinic. Used as the default for booking availability."
        actions={
          <Button onClick={onSave} disabled={update.isPending}>
            {update.isPending ? "Saving…" : "Save"}
          </Button>
        }
      />
      <Card>
        <CardContent>
          {isLoading && !rows ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <WeeklyScheduleEditor value={value} onChange={setRows} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
