"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import { OtpInput } from "@/features/chat/components/otp-input";
import { getApiErrorMessage } from "@/lib/api/client";
import { isValidOtpCode } from "@/lib/contact-validation";
import { normalizePhone, validatePhone } from "@/lib/phone";
import { widgetAuthService } from "@/services";

const RESEND_COOLDOWN_SECONDS = 30;

export function VerifyIdentity({
  clinicSlug,
  sessionToken,
  onSessionToken,
  onVerified,
  completed = false,
}: {
  clinicSlug: string;
  sessionToken: string | null;
  /** Persist the chat session token returned by OTP send so verify +
   * appointment CRUD hit the same ChatSession. */
  onSessionToken?: (token: string) => void;
  onVerified: (sessionToken: string) => void;
  /** Set once the widget has recorded this exact message as verified —
   * mirrors BookingWizard's own inert-summary treatment (Phase 22) so an
   * old verify card doesn't stay a live, re-submittable form once
   * whatever it unlocked (e.g. an appointments list) has already shown. */
  completed?: boolean;
}) {
  const [contact, setContact] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<"contact" | "code">("contact");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  // Prefer the live token from OTP send over the prop — send may mint a
  // session when the parent still has null (e.g. staff chat before first OTP).
  const [activeSessionToken, setActiveSessionToken] = useState<string | null>(
    sessionToken
  );

  useEffect(() => {
    if (sessionToken) setActiveSessionToken(sessionToken);
  }, [sessionToken]);

  function rememberSessionToken(token: string | null | undefined) {
    if (!token) return;
    setActiveSessionToken(token);
    onSessionToken?.(token);
  }

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  if (completed) {
    return (
      <ChatInlineCard className="flex items-center gap-2 rounded-[18px] border border-border/80 bg-card px-3.5 py-2.5 shadow-[0_2px_12px_rgb(11_14_46/0.06)]">
        <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700 text-xs">
          ✓
        </span>
        <p className="text-sm font-medium text-foreground">Identity verified</p>
      </ChatInlineCard>
    );
  }

  function contactIsValid(): boolean {
    return validatePhone(contact, { required: true }) === null;
  }

  async function sendCode(isResend = false) {
    if (loading || resending) return;
    if (!contactIsValid()) {
      setFieldError("Enter a valid phone number.");
      return;
    }
    setFieldError(null);
    setError(null);
    if (isResend) setResending(true);
    else setLoading(true);
    try {
      const result = await widgetAuthService.sendOtp({
        clinic_slug: clinicSlug,
        session_token: activeSessionToken,
        phone: normalizePhone(contact),
      });
      rememberSessionToken(result.session_token);
      setDebugCode(result.debug_code ?? null);
      setCode("");
      setStage("code");
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setLoading(false);
      setResending(false);
    }
  }

  async function verify() {
    if (loading) return;
    if (!isValidOtpCode(code)) {
      setFieldError("Enter the 6-digit code.");
      return;
    }
    setFieldError(null);
    setError(null);
    setLoading(true);
    try {
      const result = await widgetAuthService.verifyOtp({
        clinic_slug: clinicSlug,
        session_token: activeSessionToken,
        phone: normalizePhone(contact),
        code: code.trim(),
      });
      const token =
        result.session_token || activeSessionToken || "";
      rememberSessionToken(token);
      if (!token) {
        setError("Verification succeeded but no session was created. Please try again.");
        return;
      }
      onVerified(token);
    } catch (err) {
      setError(getApiErrorMessage(err));
      setCode("");
    } finally {
      setLoading(false);
    }
  }

  function changeContact() {
    setStage("contact");
    setCode("");
    setError(null);
    setFieldError(null);
    setCooldown(0);
  }

  return (
    <ChatInlineCard className="space-y-3 rounded-[18px] border border-border/80 bg-card p-3.5 shadow-[0_2px_12px_rgb(11_14_46/0.06)]">
      {stage === "contact" ? (
        <>
          <div>
            <p className="text-sm font-semibold text-foreground">Let&apos;s verify it&apos;s you</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {/* Trimmed: the placeholder below already says "used when
                  booking" -- repeating it here in the subtitle was the
                  unwanted-text length the phone step didn't need. */}
              For your privacy, we&apos;ll text a quick code first.
            </p>
          </div>
          <Input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            autoFocus
            value={contact}
            onChange={(e) => {
              setContact(e.target.value);
              setFieldError(null);
            }}
            placeholder="Phone number used when booking"
            className="h-9 rounded-lg text-sm"
          />
          {fieldError ? <p className="text-xs text-destructive">{fieldError}</p> : null}
          <Button
            type="button"
            size="sm"
            className="w-full rounded-lg"
            disabled={loading || !contact.trim()}
            onClick={() => void sendCode()}
          >
            {loading ? "Sending…" : "Send code"}
          </Button>
        </>
      ) : (
        <>
          <div>
            <p className="text-sm font-semibold text-foreground">Check your phone</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {/* Privacy-safe by construction, not just by wording: this
                  copy must stay true whether or not {contact} matches an
                  appointment — the backend sends an identical response
                  either way (apps/chatbot/services/otp_service.py), so a
                  wrong number gets a wrong code with no signal it was
                  wrong, exactly like a real one. Never say "we found..."
                  or reveal a count here. */}
              If {contact} has an appointment with us, a code is on its
              way.{" "}
              <button
                type="button"
                onClick={changeContact}
                className="text-primary underline-offset-2 hover:underline"
              >
                Wrong number?
              </button>
            </p>
          </div>
          <OtpInput value={code} onChange={setCode} disabled={loading} error={Boolean(error)} autoFocus />
          {debugCode ? (
            <p className="text-[11px] text-muted-foreground">Dev only — code is {debugCode}</p>
          ) : null}
          {fieldError ? <p className="text-xs text-destructive">{fieldError}</p> : null}
          <Button
            type="button"
            size="sm"
            className="w-full rounded-lg"
            disabled={loading || code.length < 1}
            onClick={() => void verify()}
          >
            {loading ? "Verifying…" : "Verify"}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Didn&apos;t receive it?{" "}
            {cooldown > 0 ? (
              <span>Resend in {cooldown}s</span>
            ) : (
              <button
                type="button"
                disabled={resending}
                onClick={() => void sendCode(true)}
                className="text-primary underline-offset-2 hover:underline disabled:opacity-50"
              >
                {resending ? "Sending…" : "Resend code"}
              </button>
            )}
          </p>
        </>
      )}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </ChatInlineCard>
  );
}
