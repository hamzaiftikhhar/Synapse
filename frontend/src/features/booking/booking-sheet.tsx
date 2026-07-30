"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2, Loader2, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { getApiErrorMessage } from "@/lib/api/client";
import { bookingService } from "@/services";
import type {
  BookingDoctor,
  BookingSlot,
  BookingSpecialty,
  BookingStepPayload,
} from "@/types/api";
import { useWidget } from "@/providers/widget-provider";

export type BookingSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  clinicSlug: string;
  initialMessage?: string;
  specialtyId?: string | null;
  specialtyName?: string | null;
  doctorId?: string | null;
  doctorName?: string | null;
  onConfirmed?: (payload: BookingStepPayload) => void;
};

export function BookingSheet({
  open,
  onOpenChange,
  clinicSlug,
  initialMessage = "",
  specialtyId = null,
  specialtyName = null,
  doctorId = null,
  doctorName = null,
  onConfirmed,
}: BookingSheetProps) {
  const { sessionToken, setSessionToken } = useWidget();
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
  });
  const [specialtyQuery, setSpecialtyQuery] = useState("");

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
  ]);

  useEffect(() => {
    if (open && clinicSlug) {
      void start();
    }
    if (!open) {
      setState(null);
      setError(null);
      setSpecialtyQuery("");
    }
  }, [open, clinicSlug]); // eslint-disable-line react-hooks/exhaustive-deps

  const runStep = useCallback(
    async (action: string, value: Record<string, unknown> = {}) => {
      if (!state?.booking_id) return;
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
        if (action === "submit_details") {
          // Auto-send OTP
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
    [state, clinicSlug, sessionToken, syncToken]
  );

  const confirm = useCallback(async () => {
    if (!state?.booking_id || !otpCode.trim()) return;
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
  }, [state, otpCode, clinicSlug, sessionToken, syncToken, onConfirmed]);

  const progress = state?.progress;
  const step = state?.step;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="mx-auto flex h-[min(92dvh,720px)] w-full max-w-lg flex-col gap-0 rounded-t-[16px] p-0 data-[side=bottom]:max-h-[min(92dvh,720px)] sm:data-[side=bottom]:max-w-lg"
      >
        <SheetHeader className="shrink-0 border-b border-border px-4 py-3 text-left">
          <div className="flex items-center justify-between gap-2">
            <div>
              <SheetTitle className="text-base text-navy">Book Appointment</SheetTitle>
              {state?.options?.doctor_name || state?.specialty_chip ? (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {[
                    state.specialty_chip?.name,
                    (state.options as { doctor_name?: string })?.doctor_name,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              ) : progress && step !== "confirmed" ? (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Step {progress.current} of {progress.total}
                </p>
              ) : null}
              {state?.specialty_chip ||
              (state?.options as { doctor_name?: string })?.doctor_name ? (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {[
                    state.specialty_chip ? "Specialty selected" : null,
                    (state?.options as { doctor_name?: string })?.doctor_name
                      ? "Doctor selected"
                      : null,
                  ]
                    .filter(Boolean)
                    .map((t) => `✓ ${t}`)
                    .join("  ")}
                </p>
              ) : null}
            </div>
            {loading ? <Loader2 className="size-4 animate-spin text-muted-foreground" /> : null}
          </div>
          {state?.specialty_chip ? (
            <button
              type="button"
              onClick={() => void runStep("clear_specialty")}
              className="mt-2 inline-flex w-fit items-center gap-1 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-navy"
            >
              {state.specialty_chip.name}
              <X className="size-3" />
            </button>
          ) : null}
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {error ? (
            <p className="mb-3 rounded-[6px] border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              {error}
            </p>
          ) : null}

          {!state && loading ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              Preparing your booking…
            </p>
          ) : null}

          {state?.guidance && step === "specialty" ? (
            <p className="mb-4 text-sm leading-relaxed text-muted-foreground">
              {state.guidance}
            </p>
          ) : null}

          {step === "specialty" && state ? (
            <SpecialtyStep
              options={state.options}
              query={specialtyQuery}
              onQuery={setSpecialtyQuery}
              onSelect={(s) =>
                void runStep("select_specialty", { id: s.id, name: s.name })
              }
            />
          ) : null}

          {step === "doctor" && state ? (
            <DoctorStep
              options={state.options}
              onSelect={(d) =>
                void runStep("select_doctor", { id: d.id, name: d.name })
              }
            />
          ) : null}

          {step === "date" && state ? (
            <DateStep
              options={state.options}
              onSelect={(date) => void runStep("select_date", { date })}
            />
          ) : null}

          {step === "time" && state ? (
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

          {step === "details" && state ? (
            <DetailsStep
              options={state.options}
              details={details}
              onChange={setDetails}
              onSubmit={() => void runStep("submit_details", details)}
              loading={loading}
            />
          ) : null}

          {step === "otp" && state ? (
            <OtpStep
              phone={(state.options.phone as string) || details.phone}
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
              onClose={() => onOpenChange(false)}
            />
          ) : null}
        </div>

        {step && step !== "confirmed" ? (
          <div className="shrink-0 border-t border-border px-4 py-3">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="gap-1"
              disabled={loading || progress?.current === 1}
              onClick={() => void runStep("back")}
            >
              <ArrowLeft className="size-3.5" />
              Back
            </Button>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
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
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-navy">
          {(options.title as string) || "Choose a specialty"}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {(options.subtitle as string) || ""}
        </p>
      </div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={
            (options.search_placeholder as string) ||
            "Condition, procedure or specialty"
          }
          className="h-10 rounded-[8px] pl-9"
        />
      </div>
      {suggested.length && !query ? (
        <div>
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Suggested for you
          </p>
          <ul className="divide-y divide-border rounded-[8px] border border-border">
            {suggested.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => onSelect(s)}
                  className="flex w-full flex-col items-start px-3 py-2.5 text-left hover:bg-muted/40"
                >
                  <span className="text-sm font-medium text-navy">
                    {s.plain_label || s.name}
                  </span>
                  {s.description ? (
                    <span className="text-xs text-muted-foreground line-clamp-1">
                      {s.description}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div>
        <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {query ? "Results" : "All specialties"}
        </p>
        <ul className="divide-y divide-border rounded-[8px] border border-border">
          {filtered.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSelect(s)}
                className="flex w-full items-center justify-between px-3 py-2.5 text-left hover:bg-muted/40"
              >
                <span className="text-sm text-navy">{s.plain_label || s.name}</span>
                {typeof s.doctor_count === "number" ? (
                  <span className="text-[11px] text-muted-foreground">
                    {s.doctor_count} doctors
                  </span>
                ) : null}
              </button>
            </li>
          ))}
          {!filtered.length ? (
            <li className="px-3 py-4 text-center text-xs text-muted-foreground">
              No matching specialties
            </li>
          ) : null}
        </ul>
      </div>
    </div>
  );
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
      <p className="text-sm font-semibold text-navy">
        {(options.title as string) || "Choose a doctor"}
      </p>
      <div className="max-h-[52dvh] space-y-2 overflow-y-auto pr-1">
        {doctors.map((d) => (
          <button
            key={d.id}
            type="button"
            onClick={() => onSelect(d)}
            className="flex w-full flex-col gap-1 rounded-[10px] border border-border bg-white p-3 text-left transition hover:border-primary/40 hover:shadow-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-navy">{d.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(d.specialties || []).slice(0, 2).join(" · ") || d.title || "Physician"}
                </p>
              </div>
              <span className="shrink-0 rounded-full bg-accent px-2 py-0.5 text-[10px] font-medium text-primary">
                Select
              </span>
            </div>
            {d.next_available ? (
              <p className="text-[11px] text-muted-foreground">
                Next available:{" "}
                <span className="font-medium text-foreground">
                  {d.next_available.label ||
                    d.next_available.time ||
                    d.next_available.start}
                </span>
              </p>
            ) : null}
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

function DateStep({
  options,
  onSelect,
}: {
  options: Record<string, unknown>;
  onSelect: (date: string) => void;
}) {
  const dates =
    (options.dates as { date: string; label: string; is_today?: boolean }[]) ||
    [];
  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-navy">
        {(options.title as string) || "Choose a date"}
      </p>
      {options.doctor_name ? (
        <p className="text-xs text-muted-foreground">
          With {String(options.doctor_name)}
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-2">
        {dates.map((d) => (
          <button
            key={d.date}
            type="button"
            onClick={() => onSelect(d.date)}
            className={cn(
              "rounded-[8px] border border-border px-3 py-3 text-left text-sm hover:border-primary/40",
              d.is_today && "border-primary/30 bg-accent/40"
            )}
          >
            {d.label}
          </button>
        ))}
      </div>
    </div>
  );
}

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
  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-navy">
        {(options.title as string) || "Choose a time"}
      </p>
      <p className="text-xs text-muted-foreground">
        {[options.doctor_name, options.date].filter(Boolean).join(" · ")}
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {slots.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onSelect(s)}
            className="rounded-[8px] border border-border px-2 py-2.5 text-center text-xs font-medium hover:border-primary/40 hover:bg-accent"
          >
            <span className="block text-navy">{s.label}</span>
            {s.doctor && !options.doctor_name ? (
              <span className="mt-0.5 block text-[10px] font-normal text-muted-foreground">
                {s.doctor}
              </span>
            ) : null}
          </button>
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
}: {
  options: Record<string, unknown>;
  details: { first_name: string; last_name: string; phone: string };
  onChange: (d: { first_name: string; last_name: string; phone: string }) => void;
  onSubmit: () => void;
  loading: boolean;
}) {
  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-navy">Almost done</p>
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
            onChange={(e) => onChange({ ...details, first_name: e.target.value })}
            className="h-9 rounded-[6px]"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Last name</Label>
          <Input
            value={details.last_name}
            onChange={(e) => onChange({ ...details, last_name: e.target.value })}
            className="h-9 rounded-[6px]"
          />
        </div>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Phone</Label>
        <Input
          value={details.phone}
          onChange={(e) => onChange({ ...details, phone: e.target.value })}
          placeholder="+1…"
          className="h-9 rounded-[6px]"
        />
      </div>
      <Button
        type="button"
        className="w-full rounded-[8px]"
        disabled={loading || !details.first_name.trim() || !details.phone.trim()}
        onClick={onSubmit}
      >
        Continue to verification
      </Button>
    </div>
  );
}

function OtpStep({
  phone,
  summary,
  code,
  onChange,
  onConfirm,
  debugCode,
  otpSent,
  loading,
}: {
  phone: string;
  summary: string;
  code: string;
  onChange: (c: string) => void;
  onConfirm: () => void;
  debugCode: string | null;
  otpSent: boolean;
  loading: boolean;
}) {
  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-semibold text-navy">Verify your phone</p>
        <p className="mt-1 text-xs text-muted-foreground">
          We sent a code to {phone || "your phone"}.
          {summary ? ` Holding: ${summary}` : ""}
        </p>
        {otpSent && debugCode ? (
          <p className="mt-2 rounded-[6px] bg-muted px-2 py-1.5 font-mono text-xs">
            Dev code: {debugCode}
          </p>
        ) : null}
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Verification code</Label>
        <Input
          value={code}
          onChange={(e) => onChange(e.target.value)}
          className="h-10 rounded-[6px] tracking-widest"
          inputMode="numeric"
          autoComplete="one-time-code"
        />
      </div>
      <Button
        type="button"
        className="w-full rounded-[8px]"
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
  onClose,
}: {
  confirmation: NonNullable<BookingStepPayload["confirmation"]>;
  onClose: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <CheckCircle2 className="size-10 text-primary" />
      <div>
        <p className="text-base font-semibold text-navy">Appointment confirmed</p>
        {confirmation.confirmation_code ? (
          <p className="mt-1 text-sm text-muted-foreground">
            Code:{" "}
            <span className="font-mono font-medium text-foreground">
              {confirmation.confirmation_code}
            </span>
          </p>
        ) : null}
        {confirmation.slot_summary ? (
          <p className="mt-2 text-xs text-muted-foreground">
            {confirmation.slot_summary}
          </p>
        ) : null}
      </div>
      <Button type="button" className="mt-4 rounded-[8px]" onClick={onClose}>
        Done
      </Button>
    </div>
  );
}
