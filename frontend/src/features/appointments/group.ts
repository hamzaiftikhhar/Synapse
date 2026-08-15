import { isoToClinicParts } from "@/lib/timezone";
import type { Appointment } from "@/types/api";

export type AppointmentDayGroup = {
  dateKey: string;
  sampleIso: string;
  rows: Appointment[];
};

export function groupAppointmentsByDay(
  rows: Appointment[],
  timeZone: string
): AppointmentDayGroup[] {
  const sorted = [...rows].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  );
  const groups: AppointmentDayGroup[] = [];
  for (const row of sorted) {
    const dateKey = isoToClinicParts(row.start_time, timeZone).date;
    const last = groups[groups.length - 1];
    if (last && last.dateKey === dateKey) {
      last.rows.push(row);
    } else {
      groups.push({ dateKey, sampleIso: row.start_time, rows: [row] });
    }
  }
  return groups;
}
