"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import { OtpInput } from "@/features/chat/components/otp-input";
import { PhoneInput } from "@/features/chat/components/phone-input";
import { getApiErrorMessage } from "@/lib/api/client";
import {
  isValidEmail,
  isValidOtpCode,
  isValidPhoneDigits,
} from "@/lib/contact-validation";
import { widgetAuthService } from "@/services";

const RESEND_COOLDOWN_SECONDS = 30;

function formatContact(method: "phone" | "email", contact: string): string {
  if (method === "email") return contact;
  // +15551234567 -> +1 555-123-4567 (best-effort, purely cosmetic)
  const match = contact.match(/^(\+\d{1,3})(\d{3})(\d{3})(\d{4})$/);
  return match ? `${match[1]} ${match[2]}-${match[3]}-${match[4]}` : contact;
}

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
  const [method, setMethod] = useState<"phone" | "email">("phone");
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
    return method === "phone" ? isValidPhoneDigits(contact) : isValidEmail(contact);
  }

  async function sendCode(isResend = false) {
    if (loading || resending) return;
    if (!contactIsValid()) {
      setFieldError(
        method === "phone"
          ? "Enter a valid phone number."
          : "Enter a valid email address."
      );
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
        phone: method === "phone" ? contact : undefined,
        email: method === "email" ? contact : undefined,
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
        phone: method === "phone" ? contact : undefined,
        email: method === "email" ? contact : undefined,
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
            <p className="text-sm font-semibold text-foreground">Verify it&apos;s you</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              We&apos;ll text or email a code to confirm it&apos;s really you before
              showing your appointments.
            </p>
          </div>
          <div className="flex gap-1.5">
            <Button
              type="button"
              size="xs"
              variant={method === "phone" ? "default" : "outline"}
              onClick={() => {
                setMethod("phone");
                setContact("");
                setFieldError(null);
              }}
            >
              Phone
            </Button>
            <Button
              type="button"
              size="xs"
              variant={method === "email" ? "default" : "outline"}
              onClick={() => {
                setMethod("email");
                setContact("");
                setFieldError(null);
              }}
            >
              Email
            </Button>
          </div>
          {method === "phone" ? (
            <PhoneInput onChange={setContact} autoFocus />
          ) : (
            <Input
              type="email"
              inputMode="email"
              autoComplete="email"
              autoFocus
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder="Email address"
              className="h-9 rounded-lg text-sm"
            />
          )}
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
            <p className="text-sm font-semibold text-foreground">Verify your identity</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              We sent a code to {formatContact(method, contact)}.{" "}
              <button
                type="button"
                onClick={changeContact}
                className="text-primary underline-offset-2 hover:underline"
              >
                Not you?
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
