"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { APP_NAME } from "@/constants";
import { getApiErrorMessage } from "@/lib/api/client";
import { authService } from "@/services";

function VerifyEmailInner() {
  const search = useSearchParams();
  const router = useRouter();
  const token = search.get("token") || "";
  const email = search.get("email") || "";
  const [status, setStatus] = useState<"idle" | "verifying" | "done" | "error">(
    token ? "verifying" : "idle"
  );
  const [message, setMessage] = useState(
    token
      ? "Verifying your email…"
      : "We sent a verification link to your inbox. Open it to continue."
  );

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await authService.verifyEmail(token);
        if (cancelled) return;
        setStatus("done");
        setMessage(res.message || "Email verified. Sign in to create your clinic.");
        toast.success("Email verified");
        setTimeout(() => router.replace("/login"), 1200);
      } catch (err) {
        if (cancelled) return;
        setStatus("error");
        setMessage(getApiErrorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, router]);

  async function resend() {
    if (!email) {
      toast.error("Missing email — register again or sign in");
      return;
    }
    try {
      await authService.resendVerification(email);
      toast.success("Verification email resent");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-6">
      <div className="w-full max-w-[400px] rounded-[6px] border border-border bg-white p-8 text-center shadow-sm">
        <Link href="/" className="text-lg font-semibold text-navy">
          {APP_NAME}
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">
          Verify your email
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        {email ? (
          <p className="mt-1 text-xs text-muted-foreground">{email}</p>
        ) : null}
        <div className="mt-6 flex flex-col gap-2">
          {status !== "verifying" && email ? (
            <Button
              type="button"
              variant="outline"
              className="rounded-[6px]"
              onClick={() => void resend()}
            >
              Resend verification email
            </Button>
          ) : null}
          <Link
            href="/login"
            className="inline-flex h-8 items-center justify-center rounded-[6px] border border-border px-3 text-sm hover:bg-muted"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-sm">Loading…</div>}>
      <VerifyEmailInner />
    </Suspense>
  );
}
