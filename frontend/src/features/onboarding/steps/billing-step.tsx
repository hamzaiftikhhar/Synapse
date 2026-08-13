"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCreateCheckout, useSubscription } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { openPaddleCheckout } from "@/lib/paddle";
import { useAuth } from "@/providers/auth-provider";

const POLL_INTERVAL_MS = 3000;
const POLL_MAX_ATTEMPTS = 40; // ~2 minutes

function formatPrice(cents: number | null | undefined, currency: string): string {
  if (cents == null) return "";
  return (cents / 100).toLocaleString(undefined, { style: "currency", currency });
}

export function BillingStep() {
  const router = useRouter();
  const { refreshMe } = useAuth();
  const { data: sub, refetch } = useSubscription();
  const createCheckout = useCreateCheckout();
  const [starting, setStarting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [pollAttempts, setPollAttempts] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const activated = Boolean(sub?.has_access);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (activated && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
      setPolling(false);
    }
  }, [activated]);

  function startPolling() {
    setPolling(true);
    setPollAttempts(0);
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => {
      setPollAttempts((n) => {
        const next = n + 1;
        if (next >= POLL_MAX_ATTEMPTS && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        return next;
      });
      void refetch();
    }, POLL_INTERVAL_MS);
  }

  async function onActivate() {
    if (!sub?.plan) return;
    setStarting(true);
    try {
      const checkout = await createCheckout.mutateAsync({ plan_slug: sub.plan.slug });
      await openPaddleCheckout({
        environment: checkout.paddle_environment,
        priceId: checkout.paddle_price_id,
        customerId: checkout.paddle_customer_id,
        clinicId: checkout.clinic_id,
      });
      startPolling();
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not start checkout"));
    } finally {
      setStarting(false);
    }
  }

  async function onGoToDashboard() {
    await refreshMe();
    router.replace("/dashboard");
  }

  if (activated) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-success/10">
          <Check className="size-6 text-success" />
        </div>
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-navy">
            You&apos;re all set 🎉
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Your Synapse workspace is now active. Your clinic is ready to
            start using Synapse.
          </p>
        </div>
        <Button type="button" onClick={() => void onGoToDashboard()}>
          Go to Dashboard
        </Button>
      </div>
    );
  }

  if (polling) {
    const tookLong = pollAttempts >= 10; // ~30s
    return (
      <div className="space-y-4 text-center">
        <div className="mx-auto size-8 animate-pulse rounded-full bg-primary/20" />
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-navy">
            Confirming your subscription…
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {tookLong
              ? "We're still confirming your payment. You can safely leave this page — we'll keep your clinic status updated, and you can come back here anytime."
              : "This usually takes just a few seconds."}
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => void refetch()}>
          Check again
        </Button>
      </div>
    );
  }

  if (!sub?.plan) {
    return <p className="text-sm text-muted-foreground">Loading your plan…</p>;
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-primary/30 bg-primary/[0.03] p-5">
        <p className="text-xs text-muted-foreground">Your selected plan</p>
        <p className="mt-1 text-lg font-semibold text-navy">{sub.plan.name}</p>
        {sub.plan.display_price_cents != null ? (
          <p className="text-sm text-muted-foreground">
            {formatPrice(sub.plan.display_price_cents, sub.plan.display_currency)} /{" "}
            {sub.plan.billing_interval}
          </p>
        ) : null}
      </div>
      <p className="text-sm text-muted-foreground">
        Payment activates your clinic&apos;s Synapse subscription. You&apos;ll
        be redirected to a secure checkout — your setup so far is already saved.
      </p>
      <Button type="button" onClick={() => void onActivate()} disabled={starting}>
        {starting ? "Opening checkout…" : "Continue to secure payment"}
      </Button>
    </div>
  );
}
