"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import { widgetAuthService } from "@/services";

export function VerifyIdentity({
  clinicSlug,
  sessionToken,
  onVerified,
}: {
  clinicSlug: string;
  sessionToken: string | null;
  onVerified: () => void;
}) {
  const [method, setMethod] = useState<"phone" | "email">("phone");
  const [contact, setContact] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<"contact" | "code">("contact");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function sendCode() {
    if (!contact.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      await widgetAuthService.sendOtp({
        clinic_slug: clinicSlug,
        session_token: sessionToken,
        phone: method === "phone" ? contact.trim() : undefined,
        email: method === "email" ? contact.trim() : undefined,
      });
      setStage("code");
    } catch {
      setError("Couldn't send a code — check the details and try again.");
    } finally {
      setLoading(false);
    }
  }

  async function verify() {
    if (!code.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      await widgetAuthService.verifyOtp({
        clinic_slug: clinicSlug,
        session_token: sessionToken,
        phone: method === "phone" ? contact.trim() : undefined,
        email: method === "email" ? contact.trim() : undefined,
        code: code.trim(),
      });
      onVerified();
    } catch {
      setError("That code didn't match — try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <ChatInlineCard className="space-y-2.5 rounded-[18px] border border-border/80 bg-white p-3 shadow-[0_2px_12px_rgb(11_14_46/0.06)]">
      <p className="text-sm font-semibold text-foreground">Verify it&apos;s you</p>
      {stage === "contact" ? (
        <>
          <div className="flex gap-1.5">
            <Button
              type="button"
              size="xs"
              variant={method === "phone" ? "default" : "outline"}
              onClick={() => setMethod("phone")}
            >
              Phone
            </Button>
            <Button
              type="button"
              size="xs"
              variant={method === "email" ? "default" : "outline"}
              onClick={() => setMethod("email")}
            >
              Email
            </Button>
          </div>
          <Input
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            placeholder={method === "phone" ? "Phone number" : "Email address"}
            className="h-9 rounded-lg text-sm"
          />
          <Button
            type="button"
            size="sm"
            className="w-full rounded-lg"
            disabled={loading || !contact.trim()}
            onClick={() => void sendCode()}
          >
            Send code
          </Button>
        </>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            Enter the code sent to {contact}
          </p>
          <Input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Verification code"
            className="h-9 rounded-lg text-sm"
          />
          <Button
            type="button"
            size="sm"
            className="w-full rounded-lg"
            disabled={loading || !code.trim()}
            onClick={() => void verify()}
          >
            Verify
          </Button>
        </>
      )}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </ChatInlineCard>
  );
}
