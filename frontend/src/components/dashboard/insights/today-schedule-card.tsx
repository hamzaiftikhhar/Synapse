"use client";

import Link from "next/link";
import { ArrowRight, CalendarClock } from "lucide-react";
import { InsightCard } from "./insight-card";
import { Badge } from "@/components/ui/badge";
import { STATUS_BADGE_VARIANT, STATUS_LABEL } from "@/features/appointments/constants";
import { formatClinicDayHeading, formatClinicTime } from "@/lib/timezone";
import { cn } from "@/lib/utils";
import type { AnalyticsCalendarUpcoming } from "@/types/api";

function statusBadge(status: string) {
  const key = String(status || "").toLowerCase();
  return (
    <Badge variant={STATUS_BADGE_VARIANT[key] ?? "secondary"}>
      {STATUS_LABEL[key] ?? status}
    </Badge>
  );
}

function ScheduleRow({
  row,
  timeZone,
}: {
  row: AnalyticsCalendarUpcoming;
  timeZone: string;
}) {
  const meta = [row.service_name, row.doctor_name ? `Dr. ${row.doctor_name}` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="flex items-center gap-3 py-2.5">
      <span className="w-[72px] shrink-0 text-[13px] font-medium tabular-nums text-foreground">
        {formatClinicTime(row.start_time, timeZone)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium text-foreground">
          {row.patient_name || "Patient"}
        </p>
        {meta ? (
          <p className="truncate text-[12px] text-muted-foreground">{meta}</p>
        ) : null}
      </div>
      {statusBadge(row.status)}
    </div>
  );
}

export function TodayScheduleCard({
  todaySchedule,
  nextAppointment,
  timeZone,
  patientsUpcoming,
  doctorsWithUpcoming,
  isLoading,
  className,
}: {
  todaySchedule: AnalyticsCalendarUpcoming[] | undefined;
  nextAppointment: AnalyticsCalendarUpcoming | null | undefined;
  timeZone: string;
  /** Patients / providers with a live upcoming visit (any date) — kept
   * visible here rather than as their own top-level tiles. */
  patientsUpcoming?: number;
  doctorsWithUpcoming?: number;
  isLoading?: boolean;
  className?: string;
}) {
  if (isLoading) {
    return (
      <InsightCard overflow="hidden" className={cn("p-5", className)}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="h-3.5 w-36 animate-pulse rounded bg-muted" />
            <div className="mt-2 h-2.5 w-48 animate-pulse rounded bg-muted" />
          </div>
          <div className="h-3 w-24 animate-pulse rounded bg-muted" />
        </div>
        <div className="mt-4 space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 py-1">
              <div className="h-3 w-14 shrink-0 animate-pulse rounded bg-muted" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="h-3 w-[46%] animate-pulse rounded bg-muted" />
                <div className="h-2.5 w-[62%] animate-pulse rounded bg-muted" />
              </div>
              <div className="h-5 w-16 animate-pulse rounded-full bg-muted" />
            </div>
          ))}
        </div>
      </InsightCard>
    );
  }

  const rows = todaySchedule ?? [];
  const today = new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: "short",
    day: "numeric",
  }).format(new Date());
  const meta = [
    patientsUpcoming != null ? `${patientsUpcoming} ${patientsUpcoming === 1 ? "patient" : "patients"}` : null,
    doctorsWithUpcoming != null
      ? `${doctorsWithUpcoming} ${doctorsWithUpcoming === 1 ? "provider" : "providers"}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <InsightCard overflow="hidden" className={cn("p-5", className)}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[15px] font-medium text-foreground">Today&apos;s schedule</p>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            Today · {today}
            {meta ? ` · ${meta} with upcoming visits` : ""}
          </p>
        </div>
        <Link
          href="/dashboard/appointments"
          className="inline-flex shrink-0 items-center gap-1 text-[12.5px] font-medium text-primary hover:underline"
        >
          View calendar
          <ArrowRight className="size-3" />
        </Link>
      </div>

      {rows.length > 0 ? (
        <div className="mt-3 divide-y divide-border/70">
          {rows.map((row) => (
            <ScheduleRow key={row.id} row={row} timeZone={timeZone} />
          ))}
        </div>
      ) : (
        <div className="mt-4">
          <p className="text-[13px] text-muted-foreground">No appointments scheduled today.</p>
          {nextAppointment ? (
            <div className="mt-4 rounded-[10px] border border-border/70 bg-muted/30 p-3.5">
              <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <CalendarClock className="size-3.5" />
                Next appointment
              </div>
              <p className="mt-1.5 text-[12.5px] text-muted-foreground">
                {formatClinicDayHeading(nextAppointment.start_time, timeZone)} ·{" "}
                {formatClinicTime(nextAppointment.start_time, timeZone)}
              </p>
              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[13.5px] font-medium text-foreground">
                    {nextAppointment.patient_name || "Patient"}
                  </p>
                  <p className="truncate text-[12px] text-muted-foreground">
                    {[nextAppointment.service_name, nextAppointment.doctor_name ? `Dr. ${nextAppointment.doctor_name}` : ""]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                {statusBadge(nextAppointment.status)}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </InsightCard>
  );
}
