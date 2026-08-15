/** Clinic-timezone helpers. Wall-clock values are clinic-local; API datetimes are ISO UTC. */

function zonedWallAsUtc(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(instant));
  const get = (type: string) =>
    Number(parts.find((p) => p.type === type)?.value ?? "0");
  let hour = get("hour");
  if (hour === 24) hour = 0;
  return Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    hour,
    get("minute"),
    get("second")
  );
}

export function clinicLocalToIso(
  date: string,
  time: string,
  timeZone: string
): string {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  const intendedAsUtc = Date.UTC(year, month - 1, day, hour, minute, 0);
  let utc = intendedAsUtc - (zonedWallAsUtc(intendedAsUtc, timeZone) - intendedAsUtc);
  utc = intendedAsUtc - (zonedWallAsUtc(utc, timeZone) - intendedAsUtc);
  return new Date(utc).toISOString();
}

export function isoToClinicParts(
  iso: string,
  timeZone: string
): { date: string; time: string } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  let hour = get("hour");
  if (hour === "24") hour = "00";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    time: `${hour.padStart(2, "0")}:${get("minute").padStart(2, "0")}`,
  };
}

export function clinicTodayDate(timeZone: string, now = new Date()): string {
  return isoToClinicParts(now.toISOString(), timeZone).date;
}

export function startOfClinicDayIso(date: string, timeZone: string): string {
  return clinicLocalToIso(date, "00:00", timeZone);
}

export function endOfClinicDayIso(date: string, timeZone: string): string {
  return clinicLocalToIso(date, "23:59", timeZone);
}

export function addMinutesIso(iso: string, minutes: number): string {
  return new Date(new Date(iso).getTime() + minutes * 60_000).toISOString();
}

export function durationMinutes(startIso: string, endIso: string): number {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  return Math.max(5, Math.round(ms / 60_000));
}

/** Monday = 0 … Sunday = 6, matching DoctorSchedule.day_of_week. */
export function mondayFirstWeekday(date: string): number {
  const [year, month, day] = date.split("-").map(Number);
  const jsDay = new Date(Date.UTC(year, month - 1, day, 12)).getUTCDay();
  return (jsDay + 6) % 7;
}

export function formatClinicWhen(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(iso));
}

export function formatClinicTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(iso));
}

export function formatClinicDate(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(iso));
}

export function formatClinicDayHeading(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(new Date(iso));
}

/** Compact range: "4:00–4:30 AM" when both ends share AM/PM. */
export function formatClinicTimeRange(
  startIso: string,
  endIso: string,
  timeZone: string
): string {
  const start = formatClinicTime(startIso, timeZone).replace(/\u202f/g, " ");
  const end = formatClinicTime(endIso, timeZone).replace(/\u202f/g, " ");
  const startPeriod = start.slice(-2);
  const endPeriod = end.slice(-2);
  if (
    (startPeriod === "AM" || startPeriod === "PM") &&
    startPeriod === endPeriod
  ) {
    return `${start.slice(0, -3).trim()}–${end}`;
  }
  return `${start} – ${end}`;
}
