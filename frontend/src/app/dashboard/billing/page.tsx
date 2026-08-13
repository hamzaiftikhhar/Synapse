"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useCancelSubscription,
  useChangePlan,
  useCreateCheckout,
  usePlans,
  useResumeSubscription,
  useSubscription,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { openPaddleCheckout } from "@/lib/paddle";
import { useAuth } from "@/providers/auth-provider";
import { cn } from "@/lib/utils";
import type { Plan } from "@/types/api";

const PLAN_COPY: Record<
  string,
  { tagline: string; featured?: boolean; features: string[] }
> = {
  starter: {
    tagline: "Turn clinic visitors into booked patients.",
    features: [
      "1,000 chatbot conversations / month",
      "24/7 front-desk assistant",
      "New appointment booking",
      "Insurance & services answers",
    ],
  },
  growth: {
    tagline: "Automate the full front desk.",
    featured: true,
    features: [
      "5,000 chatbot conversations / month",
      "Book, reschedule, and cancel",
      "Patient verification",
      "Doctor matching & availability",
      "Analytics included",
    ],
  },
  enterprise: {
    tagline: "AI infrastructure for multi-location clinics.",
    features: [
      "Unlimited conversations",
      "Multi-clinic management",
      "Advanced appointment workflows",
      "Custom clinic knowledge",
      "Priority onboarding",
    ],
  },
};

const STATUS_LABEL: Record<string, string> = {
  incomplete: "No active plan",
  trialing: "Trial",
  active: "Active",
  past_due: "Payment past due",
  paused: "Paused",
  canceled: "Canceled",
};

const STATUS_TONE: Record<string, string> = {
  incomplete: "bg-muted text-muted-foreground",
  trialing: "bg-blue-100 text-blue-700",
  active: "bg-emerald-100 text-emerald-700",
  past_due: "bg-amber-100 text-amber-700",
  paused: "bg-amber-100 text-amber-700",
  canceled: "bg-destructive/10 text-destructive",
};

const STATUS_GUIDANCE: Record<string, string> = {
  incomplete: "Choose a plan below to activate your subscription.",
  past_due:
    "Your last payment didn't go through. Paddle will retry automatically — update your payment method if you received an email about this.",
  paused: "This subscription is paused. Contact support if you need it resumed.",
  canceled: "This subscription has ended. Choose a plan below to resubscribe.",
};

const WATCH_MS = 60_000;

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function hasDisplayPrice(plan: Plan): boolean {
  return typeof plan.display_price_cents === "number";
}

function PlanPicker({
  isOwner,
  currentPlanSlug,
  hasActiveSubscription,
  cancelScheduled,
  onCheckoutStarted,
  onPlanChangeRequested,
}: {
  isOwner: boolean;
  currentPlanSlug?: string;
  hasActiveSubscription: boolean;
  cancelScheduled: boolean;
  onCheckoutStarted?: () => void;
  onPlanChangeRequested?: () => void;
}) {
  const { data: plans, isLoading } = usePlans();
  const createCheckout = useCreateCheckout();
  const changePlan = useChangePlan();
  const [pendingSlug, setPendingSlug] = useState<string | null>(null);
  const [switchTarget, setSwitchTarget] = useState<Plan | null>(null);

  async function startCheckout(plan: Plan) {
    setPendingSlug(plan.slug);
    try {
      const checkout = await createCheckout.mutateAsync({ plan_slug: plan.slug });
      await openPaddleCheckout({
        environment: checkout.paddle_environment,
        priceId: checkout.paddle_price_id,
        customerId: checkout.paddle_customer_id,
        clinicId: checkout.clinic_id,
      });
      onCheckoutStarted?.();
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not start Paddle checkout"));
    } finally {
      setPendingSlug(null);
    }
  }

  async function confirmSwitch() {
    if (!switchTarget) return;
    setPendingSlug(switchTarget.slug);
    try {
      await changePlan.mutateAsync({ plan_slug: switchTarget.slug });
      toast.success("Paddle is updating your plan — status refreshes when confirmed.");
      onPlanChangeRequested?.();
      setSwitchTarget(null);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not change plan in Paddle"));
    } finally {
      setPendingSlug(null);
    }
  }

  function onSelect(plan: Plan) {
    if (hasActiveSubscription) {
      if (cancelScheduled) {
        toast.error("Keep the current plan first, then you can switch.");
        return;
      }
      setSwitchTarget(plan);
      return;
    }
    void startCheckout(plan);
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading plans…</p>;
  }
  if (!plans || plans.length === 0) {
    return <p className="text-sm text-muted-foreground">No plans are available yet.</p>;
  }

  const currentPlan = plans.find((p) => p.slug === currentPlanSlug);

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-3">
        {plans.map((plan) => {
          const copy = PLAN_COPY[plan.slug];
          const isCurrent = hasActiveSubscription && plan.slug === currentPlanSlug;
          const featured = Boolean(copy?.featured) && !isCurrent;
          return (
            <div
              key={plan.id}
              className={cn(
                "relative flex flex-col rounded-2xl border bg-card p-6 shadow-sm",
                isCurrent
                  ? "border-primary ring-1 ring-primary/20"
                  : featured
                    ? "border-primary/40"
                    : "border-border"
              )}
            >
              {copy?.featured ? (
                <span className="absolute -top-2.5 left-5 rounded-full bg-primary px-2 py-0.5 text-[10px] font-semibold tracking-wide text-primary-foreground uppercase">
                  Most chosen
                </span>
              ) : null}
              {isCurrent ? (
                <span className="absolute -top-2.5 right-5 rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-white uppercase">
                  Current
                </span>
              ) : null}
              <p className="text-sm font-semibold text-navy">{plan.name}</p>
              {hasDisplayPrice(plan) ? (
                <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                  {(plan.display_price_cents! / 100).toLocaleString(undefined, {
                    style: "currency",
                    currency: plan.display_currency || "USD",
                    maximumFractionDigits: 0,
                  })}
                  <span className="ml-1 text-sm font-normal text-muted-foreground">
                    / {plan.billing_interval}
                  </span>
                </p>
              ) : null}
              {copy?.tagline ? (
                <p className="mt-2 text-sm text-muted-foreground">{copy.tagline}</p>
              ) : null}
              {copy?.features?.length ? (
                <ul className="mt-5 flex-1 space-y-2.5">
                  {copy.features.map((item) => (
                    <li key={item} className="flex gap-2 text-sm text-foreground/90">
                      <Check className="mt-0.5 size-4 shrink-0 text-primary" />
                      {item}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="flex-1" />
              )}
              <Button
                className="mt-6"
                variant={isCurrent ? "outline" : featured ? "default" : "outline"}
                disabled={!isOwner || isCurrent || pendingSlug === plan.slug}
                onClick={() => onSelect(plan)}
              >
                {isCurrent
                  ? "Current plan"
                  : pendingSlug === plan.slug
                    ? "Opening Paddle…"
                    : hasActiveSubscription
                      ? "Switch to this plan"
                      : "Subscribe with Paddle"}
              </Button>
            </div>
          );
        })}
      </div>

      <Dialog open={switchTarget != null} onOpenChange={(open) => !open && setSwitchTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Change plan in Paddle</DialogTitle>
            <DialogDescription>
              {currentPlan && switchTarget
                ? `Switch from ${currentPlan.name} to ${switchTarget.name}. Paddle will prorate the difference immediately.`
                : "Paddle will update your subscription and prorate the difference immediately."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setSwitchTarget(null)}>
              Keep current plan
            </Button>
            <Button
              type="button"
              disabled={pendingSlug != null}
              onClick={() => void confirmSwitch()}
            >
              {pendingSlug ? "Updating in Paddle…" : "Confirm change"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function CurrentSubscriptionCard({
  isOwner,
  watch,
  onPaddleAction,
}: {
  isOwner: boolean;
  watch?: boolean;
  onPaddleAction?: () => void;
}) {
  const { data: sub, isLoading, refetch, isFetching } = useSubscription({
    watch,
  });
  const cancel = useCancelSubscription();
  const resume = useResumeSubscription();
  const [removeOpen, setRemoveOpen] = useState(false);

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading subscription…</p>;
  }
  if (!sub) return null;

  async function onCancel(atPeriodEnd: boolean) {
    try {
      await cancel.mutateAsync({ at_period_end: atPeriodEnd });
      toast.success(
        atPeriodEnd
          ? "Paddle will cancel at the end of this period. Access continues until then."
          : "Paddle is removing this plan now. Status updates when confirmed."
      );
      setRemoveOpen(false);
      onPaddleAction?.();
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not cancel in Paddle"));
    }
  }

  async function onKeepPlan() {
    try {
      await resume.mutateAsync();
      toast.success("Paddle will keep this plan. Status updates when confirmed.");
      onPaddleAction?.();
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not keep plan in Paddle"));
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">
              {sub.plan?.name ?? "No plan"}
            </h2>
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                STATUS_TONE[sub.status] ?? STATUS_TONE.incomplete
              )}
            >
              {STATUS_LABEL[sub.status] ?? sub.status}
            </span>
          </div>
          {sub.current_period_end ? (
            <p className="mt-1 text-sm text-muted-foreground">
              {sub.cancel_at_period_end
                ? `Access ends ${formatDate(sub.current_period_end)}`
                : `Renews ${formatDate(sub.current_period_end)}`}
            </p>
          ) : null}
          {STATUS_GUIDANCE[sub.status] ? (
            <p className="mt-1 text-sm text-muted-foreground">
              {STATUS_GUIDANCE[sub.status]}
            </p>
          ) : null}
          {watch ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Waiting for Paddle to confirm…
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            {isFetching ? "Refreshing…" : "Refresh status"}
          </Button>
          {isOwner && sub.has_access && sub.cancel_at_period_end ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={resume.isPending}
              onClick={() => void onKeepPlan()}
            >
              {resume.isPending ? "Keeping…" : "Keep this plan"}
            </Button>
          ) : null}
          {isOwner && sub.has_access && !sub.cancel_at_period_end ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRemoveOpen(true)}
            >
              Remove plan
            </Button>
          ) : null}
        </div>
      </div>
      {!isOwner ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Only the clinic owner can manage billing.
        </p>
      ) : null}

      <Dialog open={removeOpen} onOpenChange={setRemoveOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Remove plan in Paddle</DialogTitle>
            <DialogDescription>
              This cancels the Paddle subscription
              {sub.plan?.name ? ` for ${sub.plan.name}` : ""}. You can keep
              access until the current period ends, or remove it immediately.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="sm:flex-col sm:items-stretch">
            <Button
              type="button"
              disabled={cancel.isPending}
              onClick={() => void onCancel(true)}
            >
              {cancel.isPending ? "Updating Paddle…" : "Cancel at period end"}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={cancel.isPending}
              onClick={() => void onCancel(false)}
            >
              Remove immediately
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setRemoveOpen(false)}
            >
              Keep subscription
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function BillingPage() {
  const { user } = useAuth();
  const isOwner = Boolean(user?.is_clinic_owner);
  const [watching, setWatching] = useState(false);
  const { data: sub } = useSubscription({ watch: watching });

  useEffect(() => {
    if (!watching) return;
    const timer = window.setTimeout(() => setWatching(false), WATCH_MS);
    return () => window.clearTimeout(timer);
  }, [watching]);

  function watchPaddle() {
    setWatching(true);
  }

  return (
    <div>
      <PageHeader
        title="Billing"
        description="Subscription and plan management for your clinic."
      />
      <div className="space-y-6">
        <CurrentSubscriptionCard
          isOwner={isOwner}
          watch={watching}
          onPaddleAction={watchPaddle}
        />
        <div>
          <h2 className="mb-1 text-sm font-semibold">
            {sub?.has_access ? "Change plan" : "Choose a plan"}
          </h2>
          <p className="mb-3 text-xs text-muted-foreground">
            {sub?.has_access
              ? "Switching plans updates your Paddle subscription with immediate proration."
              : "Checkout opens in Paddle. Status updates here after payment is confirmed."}
          </p>
          <PlanPicker
            isOwner={isOwner}
            currentPlanSlug={sub?.plan?.slug}
            hasActiveSubscription={Boolean(sub?.has_access)}
            cancelScheduled={Boolean(sub?.cancel_at_period_end)}
            onCheckoutStarted={watchPaddle}
            onPlanChangeRequested={watchPaddle}
          />
        </div>
      </div>
    </div>
  );
}
