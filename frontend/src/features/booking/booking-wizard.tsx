"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Loader2, Search, X } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/api/client";
import { bookingService } from "@/services";
import type {
  BookingDateDensity,
  BookingDateOption,
  BookingDoctor,
  BookingSlot,
  BookingSpecialty,
  BookingStepPayload,
} from "@/types/api";
import { useWidget } from "@/providers/widget-provider";

export type BookingWizardProps = {
  clinicSlug: string;
  initialMessage?: string;
  specialtyId?: string | null;
  specialtyName?: string | null;
  doctorId?: string | null;
  doctorName?: string | null;
  /** When false, wizard is read-only / collapsed after confirm or dismiss. */
  active?: boolean;
  onConfirmed?: (payload: BookingStepPayload) => void;
  onDismiss?: () => void;
  /** Fired after every successful start() with the (stable, resumed) booking_id. */
  onStarted?: (bookingId: string) => void;
  className?: string;
};

export function BookingWizard({
  clinicSlug,
  initialMessage = "",
  specialtyId = null,
  specialtyName = null,
  doctorId = null,
  doctorName = null,
  active = true,
  onConfirmed,
  onDismiss,
  onStarted,
  className,
}: BookingWizardProps) {
  const { sessionToken, setSessionToken, config } = useWidget();
  const brandColor =
    config?.configuration?.widget?.primary_color?.trim() || undefined;
  const verificationMode =
    config?.configuration?.booking?.verification_mode || "sms";
  const [state, setState] = useState<BookingStepPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [otpSent, setOtpSent] = useState(false);
  const [details, setDetails] = useState({
    first_name: "",
    last_name: "",
    phone: "",
    email: "",
  });
  const [specialtyQuery, setSpecialtyQuery] = useState("");
  const [started, setStarted] = useState(false);

  const syncToken = useCallback(
    (payload: BookingStepPayload) => {
      if (payload.session_token) setSessionToken(payload.session_token);
    },
    [setSessionToken]
  );

  const start = useCallback(async () => {
    setLoading(true);
    setError(null);
    setOtpSent(false);
    setOtpCode("");
    setDebugCode(null);
    try {
      const payload = await bookingService.start({
        clinic_slug: clinicSlug,
        session_token: sessionToken,
        message: initialMessage,
        reason: initialMessage,
        specialty_id: specialtyId,
        specialty_name: specialtyName,
        doctor_id: doctorId,
        doctor_name: doctorName,
      });
      syncToken(payload);
      setState(payload);
      setStarted(true);
      if (payload.booking_id) onStarted?.(payload.booking_id);
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [
    clinicSlug,
    sessionToken,
    initialMessage,
    specialtyId,
    specialtyName,
    doctorId,
    doctorName,
    syncToken,
    onStarted,
  ]);

  useEffect(() => {
    if (active && clinicSlug && !started) {
      void start();
    }
  }, [active, clinicSlug, started, start]);

  // Chat resolved a new doctor/specialty for this same booking (e.g. "actually
  // Dr. Y") — re-call start() so the (now resume-safe) backend updates the
  // existing draft in place rather than the UI going stale.
  const prevHints = useRef({ specialtyId, doctorId });
  useEffect(() => {
    if (!started) return;
    if (
      prevHints.current.specialtyId === specialtyId &&
      prevHints.current.doctorId === doctorId
    ) {
      return;
    }
    prevHints.current = { specialtyId, doctorId };
    void start();
  }, [started, specialtyId, doctorId, start]);

  const runStep = useCallback(
    async (action: string, value: Record<string, unknown> = {}) => {
      if (!active || !state?.booking_id) return;
      setLoading(true);
      setError(null);
      try {
        const payload = await bookingService.step({
          clinic_slug: clinicSlug,
          session_token: state.session_token || sessionToken || "",
          booking_id: state.booking_id,
          action,
          value,
        });
        syncToken(payload);
        setState(payload);
        if (payload.stale_hero) {
          setError("That time was just taken — pick another below.");
        }
        if (payload.step === "confirmed") {
          onConfirmed?.(payload);
        } else if (action === "submit_details" && payload.step === "otp") {
          const otp = await bookingService.sendOtp({
            clinic_slug: clinicSlug,
            session_token: payload.session_token || sessionToken || "",
            booking_id: payload.booking_id,
          });
          setOtpSent(true);
          setDebugCode(otp.debug_code ?? null);
        }
      } catch (e) {
        setError(getApiErrorMessage(e));
      } finally {
        setLoading(false);
      }
    },
    [active, state, clinicSlug, sessionToken, syncToken, onConfirmed]
  );

  const confirm = useCallback(async () => {
    if (!active || !state?.booking_id || !otpCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const payload = await bookingService.confirm({
        clinic_slug: clinicSlug,
        session_token: state.session_token || sessionToken || "",
        booking_id: state.booking_id,
        otp_code: otpCode.trim(),
      });
      syncToken(payload);
      setState(payload);
      onConfirmed?.(payload);
    } catch (e) {
      setError(getApiErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [
    active,
    state,
    otpCode,
    clinicSlug,
    sessionToken,
    syncToken,
    onConfirmed,
  ]);

  const progress = state?.progress;
  const step = state?.step;
  const interactive = active && step !== "confirmed";

  return (
    <div className={cn("flex flex-col", className)}>
      <div className="flex items-start justify-between gap-2 border-b border-border/70 px-3.5 py-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">Book Appointment</p>
          {step !== "path" && (state?.options?.doctor_name || state?.specialty_chip) ? (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {[
                state.specialty_chip?.name,
                (state.options as { doctor_name?: string })?.doctor_name,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ) : progress && step !== "confirmed" && step !== "path" && (progress.current ?? 0) > 0 ? (
            <p className="mt-0.5 text-xs text-muted-foreground">
              Step {progress.current} of {progress.total}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {loading ? (
            <Loader2 className="size-4 animate-spin text-muted-foreground" />
          ) : null}
          {onDismiss && interactive ? (
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              aria-label="Dismiss booking"
            >
              <X className="size-4" />
            </button>
          ) : null}
        </div>
      </div>

      {state?.specialty_chip && interactive ? (
        <div className="border-b border-border/50 px-3.5 py-2">
          <button
            type="button"
            onClick={() => void runStep("clear_specialty")}
            className="inline-flex w-fit items-center gap-1 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground"
          >
            {state.specialty_chip.name}
            <X className="size-3" />
          </button>
        </div>
      ) : null}

      <div className="min-h-0 max-h-[min(52dvh,420px)] overflow-y-auto px-3.5 py-3">
        {error ? (
          <p className="mb-3 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        ) : null}

        {!state && loading ? (
          <p className="py-10 text-center text-sm text-muted-foreground">
            Preparing your booking…
          </p>
        ) : null}

        {state?.guidance && step === "specialty" ? (
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
            {state.guidance}
          </p>
        ) : null}

        {step === "path" && state && interactive ? (
          <PathStep
            options={state.options}
            onSelectPath={(path, specialty) =>
              void runStep("select_path", {
                path,
                ...(specialty
                  ? { specialty_id: specialty.id, specialty_name: specialty.name }
                  : {}),
              })
            }
          />
        ) : null}

        {step === "specialty" && state && interactive ? (
          <SpecialtyStep
            options={state.options}
            query={specialtyQuery}
            onQuery={setSpecialtyQuery}
            onSelect={(s) =>
              void runStep("select_specialty", { id: s.id, name: s.name })
            }
          />
        ) : null}

        {step === "doctor" && state && interactive ? (
          <DoctorStep
            options={state.options}
            onSelect={(d) =>
              void runStep("select_doctor", { id: d.id, name: d.name })
            }
          />
        ) : null}

        {step === "date" && state && interactive ? (
          <DateStep
            options={state.options}
            onSelect={(date) => void runStep("select_date", { date })}
          />
        ) : null}

        {step === "time" && state && interactive ? (
          <TimeStep
            options={state.options}
            onSelect={(slot) =>
              void runStep("select_time", {
                start: slot.start,
                end: slot.end,
                doctor_id: slot.doctor_id,
                doctor: slot.doctor,
              })
            }
            onMore={() => void runStep("more_times")}
          />
        ) : null}

        {step === "details" && state && interactive ? (
          <DetailsStep
            options={state.options}
            details={details}
            onChange={setDetails}
            onSubmit={() => void runStep("submit_details", details)}
            loading={loading}
            verificationMode={
              (state.options.verification_mode as string) || verificationMode
            }
          />
        ) : null}

        {step === "otp" && state && interactive ? (
          <OtpStep
            phone={(state.options.phone as string) || details.phone}
            email={(state.options.email as string) || details.email}
            verificationMode={
              (state.options.verification_mode as string) || verificationMode
            }
            summary={(state.options.slot_summary as string) || ""}
            code={otpCode}
            onChange={setOtpCode}
            onConfirm={() => void confirm()}
            debugCode={debugCode}
            otpSent={otpSent}
            loading={loading}
          />
        ) : null}

        {step === "confirmed" && state?.confirmation ? (
          <ConfirmedStep
            confirmation={state.confirmation}
            patientFirstName={
              details.first_name || state.confirmation.first_name || ""
            }
            brandColor={brandColor}
            onClose={onDismiss}
          />
        ) : null}

        {!active && step !== "confirmed" ? (
          <p className="py-6 text-center text-xs text-muted-foreground">
            Booking closed. Ask to book again anytime.
          </p>
        ) : null}
      </div>

      {interactive && step && step !== "path" ? (
        <div className="shrink-0 border-t border-border/70 px-3.5 py-2.5">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-1"
            disabled={loading}
            onClick={() => void runStep("back")}
          >
            <ArrowLeft className="size-3.5" />
            Back
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function PathStep({
  options,
  onSelectPath,
}: {
  options: Record<string, unknown>;
  onSelectPath: (
    path: "first_available" | "help_choose" | "know_doctor",
    specialty?: BookingSpecialty
  ) => void;
}) {
  const paths =
    (options.paths as {
      id: string;
      title: string;
      recommended?: boolean;
    }[]) || [];

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-foreground">
        {(options.title as string) || "How would you like to book?"}
      </p>
      {paths.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() =>
            onSelectPath(p.id as "first_available" | "help_choose" | "know_doctor")
          }
          className={cn(
            "flex w-full items-center rounded-lg border px-3 py-3 text-left text-sm font-medium transition-colors",
            p.recommended
              ? "border-primary/35 bg-primary/[0.04] hover:bg-primary/[0.08]"
              : "border-border bg-background hover:bg-muted/40"
          )}
        >
          {p.title}
        </button>
      ))}
    </div>
  );
}

function SpecialtyStep({
  options,
  query,
  onQuery,
  onSelect,
}: {
  options: Record<string, unknown>;
  query: string;
  onQuery: (q: string) => void;
  onSelect: (s: BookingSpecialty) => void;
}) {
  const suggested = (options.suggested as BookingSpecialty[]) || [];
  const all = (options.all as BookingSpecialty[]) || [];
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.description || "").toLowerCase().includes(q) ||
        (s.plain_label || "").toLowerCase().includes(q)
    );
  }, [all, query]);

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-foreground">
        {(options.title as string) || "Choose a specialty"}
      </p>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={
            (options.search_placeholder as string) || "Search"
          }
          className="h-9 rounded-lg pl-9 text-sm"
        />
      </div>
      <ul className="divide-y divide-border rounded-lg border border-border max-h-48 overflow-y-auto">
        {(query ? filtered : suggested.length ? suggested : filtered).map((s) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => onSelect(s)}
              className="flex w-full items-center justify-between px-3 py-2.5 text-left text-sm transition-colors hover:bg-accent/60"
            >
              <span>{s.plain_label || s.name}</span>
            </button>
          </li>
        ))}
        {!filtered.length && query ? (
          <li className="px-3 py-4 text-center text-xs text-muted-foreground">
            No matches
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function doctorInitials(name: string): string {
  const parts = name.replace(/^dr\.?\s*/i, "").trim().split(/\s+/);
  const letters = parts.slice(0, 2).map((p) => p[0]?.toUpperCase() || "");
  return letters.join("") || "?";
}

function DoctorStep({
  options,
  onSelect,
}: {
  options: Record<string, unknown>;
  onSelect: (d: BookingDoctor) => void;
}) {
  const doctors = (options.doctors as BookingDoctor[]) || [];
  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-foreground">
        {(options.title as string) || "Choose a doctor"}
      </p>
      <div className="space-y-1.5">
        {doctors.map((d) => (
          <button
            key={d.id}
            type="button"
            onClick={() => onSelect(d)}
            className="flex w-full items-center gap-3 rounded-xl border border-border bg-white px-3 py-2 text-left transition-[border-color,box-shadow] hover:border-primary/40 hover:shadow-sm"
          >
            <Avatar>
              {d.photo_url ? <AvatarImage src={d.photo_url} alt={d.name} /> : null}
              <AvatarFallback>{doctorInitials(d.name)}</AvatarFallback>
            </Avatar>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-foreground">
                {d.name}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {[
                  (d.specialties || [])[0] || d.title || "Physician",
                  d.next_available?.label || d.next_available?.time,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </span>
            {/* Whole row is the click target — a real nested <button> here
                would be invalid HTML, so this is a styled, non-interactive
                pill (upgraded from the old passive "Select" pill). */}
            <span className="shrink-0 rounded-full bg-primary px-3 py-1 text-[11px] font-medium text-primary-foreground">
              Reserve
            </span>
          </button>
        ))}
        {!doctors.length ? (
          <p className="py-8 text-center text-xs text-muted-foreground">
            {(options.empty_message as string) || "No doctors available"}
          </p>
        ) : null}
      </div>
    </div>
  );
}

const DENSITY_CELL_STYLES: Record<BookingDateDensity, string> = {
  plenty:
    "border-emerald-200 bg-emerald-50/70 hover:border-emerald-300 dark:border-emerald-900/40 dark:bg-emerald-950/20",
  few: "border-amber-200 bg-amber-50/70 hover:border-amber-300 dark:border-amber-900/40 dark:bg-amber-950/20",
  almost_full:
    "border-rose-200 bg-rose-50/60 hover:border-rose-300 dark:border-rose-900/40 dark:bg-rose-950/20",
  closed: "border-border bg-muted/30 text-muted-foreground/40 cursor-not-allowed",
};

const DENSITY_DOT_STYLES: Record<BookingDateDensity, string> = {
  plenty: "bg-emerald-500",
  few: "bg-amber-500",
  almost_full: "bg-rose-500",
  closed: "bg-transparent",
};

const WEEKDAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];

function DateStep({
  options,
  onSelect,
}: {
  options: Record<string, unknown>;
  onSelect: (date: string) => void;
}) {
  const dates = (options.dates as BookingDateOption[]) || [];
  const selectedDate = (options.selected_date as string | null) || null;
  const selectedRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedDate]);

  const leadingBlanks = dates.length
    ? new Date(`${dates[0].date}T12:00:00`).getDay()
    : 0;

  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-foreground">
        {(options.title as string) || "Choose a date"}
      </p>
      {options.hint ? (
        <p className="text-xs text-muted-foreground">{String(options.hint)}</p>
      ) : null}
      {options.doctor_name ? (
        <p className="text-xs text-muted-foreground">
          With {String(options.doctor_name)}
        </p>
      ) : null}
      <div className="max-h-52 overflow-y-auto rounded-lg border border-border/60 p-1.5">
        <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-medium text-muted-foreground">
          {WEEKDAY_LABELS.map((w, i) => (
            <div key={i} className="py-1">
              {w}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: leadingBlanks }).map((_, i) => (
            <div key={`blank-${i}`} aria-hidden />
          ))}
          {dates.map((d) => {
            const density = d.density || "plenty";
            const closed = density === "closed";
            const isSelected = d.date === selectedDate;
            return (
              <button
                key={d.date}
                ref={isSelected ? selectedRef : undefined}
                type="button"
                disabled={closed}
                onClick={() => onSelect(d.date)}
                title={
                  closed
                    ? d.reason === "closed"
                      ? "Clinic closed"
                      : "No availability"
                    : undefined
                }
                className={cn(
                  "relative aspect-square rounded-md border text-[11px] transition-colors",
                  DENSITY_CELL_STYLES[density],
                  d.is_today && !closed && "font-semibold text-primary",
                  isSelected && "ring-2 ring-primary/50"
                )}
              >
                {Number(d.date.slice(-2))}
                {!closed ? (
                  <span
                    className={cn(
                      "absolute bottom-1 left-1/2 size-1 -translate-x-1/2 rounded-full",
                      DENSITY_DOT_STYLES[density]
                    )}
                    aria-hidden
                  />
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-emerald-500" /> Plenty
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-amber-500" /> Few left
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-rose-500" /> Almost full
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-muted-foreground/30" /> Unavailable
        </span>
      </div>
    </div>
  );
}

function slotHour(slot: BookingSlot): number | null {
  // Read the wall-clock hour directly from the ISO string (already in
  // clinic-local time from the backend) — never Date.getHours(), which
  // would silently convert to the browser's local timezone instead.
  const match = /T(\d{2}):/.exec(slot.start || "");
  return match ? Number(match[1]) : null;
}

function timeBucket(hour: number | null): 0 | 1 | 2 {
  if (hour == null) return 0;
  if (hour < 12) return 0;
  if (hour < 17) return 1;
  return 2;
}

const TIME_SECTION_LABELS = ["Morning", "Afternoon", "Evening"] as const;

function TimeStep({
  options,
  onSelect,
  onMore,
}: {
  options: Record<string, unknown>;
  onSelect: (slot: BookingSlot) => void;
  onMore: () => void;
}) {
  const slots = (options.slots as BookingSlot[]) || [];
  const hasMore = Boolean(options.has_more);
  const timeHintUnmet = Boolean(options.time_hint_unmet);
  const timeHint = (options.time_hint as string | null) || null;

  const sections = useMemo(() => {
    const groups: BookingSlot[][] = [[], [], []];
    for (const s of slots) groups[timeBucket(slotHour(s))].push(s);
    return TIME_SECTION_LABELS.map((label, i) => ({
      key: i,
      label,
      slots: groups[i],
    })).filter((g) => g.slots.length);
  }, [slots]);

  const activeSectionKey = useMemo(() => {
    if (!timeHint) return null;
    const hour = Number(timeHint.slice(0, 2));
    return Number.isNaN(hour) ? null : timeBucket(hour);
  }, [timeHint]);

  const activeSectionRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    activeSectionRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeSectionKey, slots]);

  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-foreground">
        {(options.title as string) || "Choose a time"}
      </p>
      <p className="text-xs text-muted-foreground">
        {options.clinic_assigned
          ? "Clinic will confirm the doctor with your slot"
          : [options.doctor_name, options.date].filter(Boolean).join(" · ")}
        {options.clinic_assigned && options.date
          ? ` · ${String(options.date)}`
          : null}
      </p>
      {timeHintUnmet ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50/70 px-2.5 py-1.5 text-[11px] text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300">
          No times matched your preferred time — showing all available times instead.
        </p>
      ) : null}
      <div className="max-h-80 space-y-4 overflow-y-auto">
        {sections.map((section) => (
          <div
            key={section.key}
            ref={section.key === activeSectionKey ? activeSectionRef : undefined}
          >
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {section.label}
            </p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {section.slots.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => onSelect(s)}
                  className="rounded-xl border border-border px-2 py-2.5 text-center text-xs font-medium transition-[border-color,background-color] hover:border-primary/40 hover:bg-accent"
                >
                  <span className="block text-foreground">{s.label}</span>
                  {s.doctor && !options.doctor_name ? (
                    <span className="mt-0.5 block text-[10px] font-normal text-muted-foreground">
                      {s.doctor}
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {!slots.length ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          No times available this day. Go back and pick another date.
        </p>
      ) : null}
      {hasMore ? (
        <Button type="button" variant="outline" className="w-full" onClick={onMore}>
          More times
        </Button>
      ) : null}
    </div>
  );
}

function DetailsStep({
  options,
  details,
  onChange,
  onSubmit,
  loading,
  verificationMode = "sms",
}: {
  options: Record<string, unknown>;
  details: {
    first_name: string;
    last_name: string;
    phone: string;
    email: string;
  };
  onChange: (d: {
    first_name: string;
    last_name: string;
    phone: string;
    email: string;
  }) => void;
  onSubmit: () => void;
  loading: boolean;
  verificationMode?: string;
}) {
  const needPhone =
    verificationMode === "sms" ||
    verificationMode === "sms_or_email" ||
    verificationMode === "none";
  const needEmail =
    verificationMode === "email" ||
    verificationMode === "sms_or_email" ||
    verificationMode === "none";
  const phoneRequired = verificationMode === "sms";
  const emailRequired = verificationMode === "email";
  const contactOk =
    (phoneRequired ? details.phone.trim() : true) &&
    (emailRequired ? details.email.trim() : true) &&
    (verificationMode === "sms_or_email" || verificationMode === "none"
      ? Boolean(details.phone.trim() || details.email.trim())
      : true);

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-foreground">Almost done</p>
        {options.slot_summary ? (
          <p className="mt-1 text-xs text-muted-foreground">
            {String(options.slot_summary)}
          </p>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">First name</Label>
          <Input
            value={details.first_name}
            onChange={(e) =>
              onChange({ ...details, first_name: e.target.value })
            }
            className="h-9 rounded-xl"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Last name</Label>
          <Input
            value={details.last_name}
            onChange={(e) =>
              onChange({ ...details, last_name: e.target.value })
            }
            className="h-9 rounded-xl"
          />
        </div>
      </div>
      {needPhone ? (
        <div className="space-y-1">
          <Label className="text-xs">
            Phone{phoneRequired ? "" : " (optional if email provided)"}
          </Label>
          <Input
            value={details.phone}
            onChange={(e) => onChange({ ...details, phone: e.target.value })}
            placeholder="+1…"
            className="h-9 rounded-xl"
          />
        </div>
      ) : null}
      {needEmail ? (
        <div className="space-y-1">
          <Label className="text-xs">
            Email{emailRequired ? "" : " (optional if phone provided)"}
          </Label>
          <Input
            type="email"
            value={details.email}
            onChange={(e) => onChange({ ...details, email: e.target.value })}
            className="h-9 rounded-xl"
          />
        </div>
      ) : null}
      <Button
        type="button"
        className="w-full rounded-xl"
        disabled={loading || !details.first_name.trim() || !contactOk}
        onClick={onSubmit}
      >
        {verificationMode === "none"
          ? "Confirm appointment"
          : "Continue to verification"}
      </Button>
    </div>
  );
}

function OtpStep({
  phone,
  email,
  verificationMode = "sms",
  summary,
  code,
  onChange,
  onConfirm,
  debugCode,
  otpSent,
  loading,
}: {
  phone: string;
  email?: string;
  verificationMode?: string;
  summary: string;
  code: string;
  onChange: (c: string) => void;
  onConfirm: () => void;
  debugCode: string | null;
  otpSent: boolean;
  loading: boolean;
}) {
  const dest =
    verificationMode === "email"
      ? email || "your email"
      : verificationMode === "sms_or_email"
        ? phone || email || "your contact"
        : phone || "your phone";

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-foreground">
          Verify your {verificationMode === "email" ? "email" : "identity"}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          We sent a code to {dest}.
          {summary ? ` Holding: ${summary}` : ""}
        </p>
        {otpSent && debugCode ? (
          <p className="mt-2 rounded-xl bg-muted px-2 py-1.5 font-mono text-xs">
            Dev code: {debugCode}
          </p>
        ) : null}
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Verification code</Label>
        <Input
          value={code}
          onChange={(e) => onChange(e.target.value)}
          className="h-10 rounded-xl tracking-widest"
          inputMode="numeric"
          autoComplete="one-time-code"
        />
      </div>
      <Button
        type="button"
        className="w-full rounded-xl"
        disabled={loading || code.trim().length < 4}
        onClick={onConfirm}
      >
        Confirm appointment
      </Button>
    </div>
  );
}

function ConfirmedStep({
  confirmation,
  patientFirstName,
  brandColor,
  onClose,
}: {
  confirmation: NonNullable<BookingStepPayload["confirmation"]>;
  patientFirstName?: string;
  brandColor?: string;
  onClose?: () => void;
}) {
  const accent = brandColor || "var(--primary)";
  const name = (patientFirstName || confirmation.first_name || "").trim();
  const headline = name
    ? `${name}, we've got you confirmed for your appointment.`
    : "We've got you confirmed for your appointment.";

  const timeLabel = formatConfirmTime(confirmation.start);
  const dateLabel = formatConfirmDate(confirmation.date);
  const doctor = confirmation.doctor_name?.trim();
  const primaryLine = [timeLabel, doctor].filter(Boolean).join("  ·  ");

  return (
    <div className="flex flex-col items-center gap-4 px-1 py-6 text-center">
      <CalendarCheckIcon color={accent} />
      <div className="space-y-2">
        <p className="text-[15px] font-semibold leading-snug text-foreground">
          {headline}
        </p>
        {primaryLine ? (
          <p className="text-base font-semibold tracking-tight text-foreground">
            {primaryLine}
          </p>
        ) : confirmation.slot_summary ? (
          <p className="text-sm font-medium text-foreground">
            {confirmation.slot_summary}
          </p>
        ) : null}
        {dateLabel ? (
          <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            {dateLabel}
          </p>
        ) : null}
        {confirmation.confirmation_code ? (
          <p className="pt-1 text-xs text-muted-foreground">
            Code{" "}
            <span className="font-mono font-semibold text-foreground">
              {confirmation.confirmation_code}
            </span>
          </p>
        ) : null}
      </div>
      {onClose ? (
        <Button
          type="button"
          className="mt-1 w-full rounded-xl text-primary-foreground"
          style={{ backgroundColor: brandColor || undefined }}
          onClick={onClose}
        >
          Done
        </Button>
      ) : null}
    </div>
  );
}

function CalendarCheckIcon({ color }: { color: string }) {
  return (
    <div className="relative flex size-14 items-center justify-center" aria-hidden>
      <svg viewBox="0 0 48 48" className="size-14">
        <rect
          x="6"
          y="10"
          width="36"
          height="32"
          rx="6"
          fill="none"
          stroke={color}
          strokeWidth="2.25"
        />
        <path
          d="M6 18h36"
          fill="none"
          stroke={color}
          strokeWidth="2.25"
          strokeLinecap="round"
        />
        <path
          d="M16 6v8M32 6v8"
          fill="none"
          stroke={color}
          strokeWidth="2.25"
          strokeLinecap="round"
        />
        <rect x="10" y="22" width="28" height="16" rx="2" fill={`${cssColorWithAlpha(color, 0.12)}`} />
      </svg>
      <span
        className="absolute bottom-1 right-0 flex size-6 items-center justify-center rounded-full text-white shadow-sm"
        style={{ backgroundColor: color }}
      >
        <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden>
          <path
            d="M3.5 8.2 6.4 11l6-7"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    </div>
  );
}

function cssColorWithAlpha(color: string, alpha: number): string {
  const c = color.trim();
  if (c.startsWith("#") && (c.length === 7 || c.length === 4)) {
    const hex =
      c.length === 4
        ? `#${c[1]}${c[1]}${c[2]}${c[2]}${c[3]}${c[3]}`
        : c;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    if ([r, g, b].every((n) => !Number.isNaN(n))) {
      return `rgba(${r},${g},${b},${alpha})`;
    }
  }
  return `color-mix(in oklab, ${c} ${Math.round(alpha * 100)}%, transparent)`;
}

function formatConfirmDate(raw?: string | null): string {
  if (!raw) return "";
  const d = new Date(`${raw}T12:00:00`);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function formatConfirmTime(raw?: string | null): string {
  if (!raw) return "";
  // ISO or HH:MM
  const asDate = new Date(raw);
  if (!Number.isNaN(asDate.getTime()) && raw.includes("T")) {
    return asDate.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  }
  const m = raw.match(/(\d{1,2}):(\d{2})/);
  if (m) {
    const h = Number(m[1]);
    const min = m[2];
    const ampm = h >= 12 ? "PM" : "AM";
    const h12 = ((h + 11) % 12) + 1;
    return `${h12}:${min} ${ampm}`;
  }
  return raw;
}
