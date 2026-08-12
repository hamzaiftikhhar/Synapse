"use client";

import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import {
  useCancelSubscription,
  useChangePlan,
  useCreateCheckout,
  usePlans,
  useSubscription,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { openPaddleCheckout } from "@/lib/paddle";
import { useAuth } from "@/providers/auth-provider";
import { cn } from "@/lib/utils";
import type { Plan } from "@/types/api";

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
  paused: "This subscription is paused. Contact support if this is unexpected.",
  canceled: "This subscription has ended. Choose a plan below to resubscribe.",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function formatPrice(plan: Plan): string {
  if (plan.display_price_cents == null) return "";
  const amount = (plan.display_price_cents / 100).toLocaleString(undefined, {
    style: "currency",
    currency: plan.display_currency || "USD",
  });
  return `${amount} / ${plan.billing_interval}`;
}

function PlanPicker({
  isOwner,
  currentPlanSlug,
  hasActiveSubscription,
}: {
  isOwner: boolean;
  currentPlanSlug?: string;
  hasActiveSubscription: boolean;
}) {
  const { data: plans, isLoading } = usePlans();
  const createCheckout = useCreateCheckout();
  const changePlan = useChangePlan();
  const [pendingSlug, setPendingSlug] = useState<string | null>(null);

  async function onSelect(plan: Plan) {
    setPendingSlug(plan.slug);
    try {
      if (hasActiveSubscription) {
        // Existing Paddle subscription — update its price directly, no
        // Checkout overlay needed. Local state stays as-is until the
        // resulting webhook confirms the change.
        await changePlan.mutateAsync({ plan_slug: plan.slug });
        toast.success("Plan change requested");
      } else {
        const checkout = await createCheckout.mutateAsync({ plan_slug: plan.slug });
        await openPaddleCheckout({
          environment: checkout.paddle_environment,
          priceId: checkout.paddle_price_id,
          customerId: checkout.paddle_customer_id,
        });
      }
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not update plan"));
    } finally {
      setPendingSlug(null);
    }
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading plans…</p>;
  }
  if (!plans || plans.length === 0) {
    return <p className="text-sm text-muted-foreground">No plans are available yet.</p>;
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {plans.map((plan) => {
        const isCurrent = hasActiveSubscription && plan.slug === currentPlanSlug;
        return (
          <div
            key={plan.id}
            className={cn(
              "flex flex-col gap-3 rounded-2xl border bg-card p-5",
              isCurrent ? "border-primary" : "border-border"
            )}
          >
            <div>
              <h3 className="text-sm font-semibold">{plan.name}</h3>
              {formatPrice(plan) ? (
                <p className="mt-1 text-lg font-semibold text-foreground">
                  {formatPrice(plan)}
                </p>
              ) : null}
            </div>
            <Button
              className="mt-auto"
              variant={isCurrent ? "outline" : "default"}
              disabled={!isOwner || isCurrent || pendingSlug === plan.slug}
              onClick={() => onSelect(plan)}
            >
              {isCurrent
                ? "Current plan"
                : pendingSlug === plan.slug
                  ? "Please wait…"
                  : hasActiveSubscription
                    ? "Switch to this plan"
                    : "Subscribe"}
            </Button>
          </div>
        );
      })}
    </div>
  );
}

function CurrentSubscriptionCard({ isOwner }: { isOwner: boolean }) {
  const { data: sub, isLoading, refetch, isFetching } = useSubscription();
  const cancel = useCancelSubscription();
  const [confirmingCancel, setConfirmingCancel] = useState(false);

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading subscription…</p>;
  }
  if (!sub) return null;

  async function onCancel() {
    try {
      await cancel.mutateAsync({ at_period_end: true });
      toast.success("Cancellation requested — access continues until the current period ends.");
      setConfirmingCancel(false);
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Could not cancel subscription"));
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
          {isOwner && sub.has_access && !sub.cancel_at_period_end ? (
            confirmingCancel ? (
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setConfirmingCancel(false)}
                >
                  Keep subscription
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  disabled={cancel.isPending}
                  onClick={onCancel}
                >
                  {cancel.isPending ? "Canceling…" : "Confirm cancel"}
                </Button>
              </div>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setConfirmingCancel(true)}
              >
                Cancel subscription
              </Button>
            )
          ) : null}
        </div>
      </div>
      {!isOwner ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Only the clinic owner can manage billing.
        </p>
      ) : null}
    </div>
  );
}

export default function BillingPage() {
  const { user } = useAuth();
  const isOwner = Boolean(user?.is_clinic_owner);
  const { data: sub } = useSubscription();

  return (
    <div>
      <PageHeader
        title="Billing"
        description="Subscription and plan management for your clinic."
      />
      <div className="space-y-6">
        <CurrentSubscriptionCard isOwner={isOwner} />
        <div>
          <h2 className="mb-3 text-sm font-semibold">
            {sub?.has_access ? "Change plan" : "Choose a plan"}
          </h2>
          <PlanPicker
            isOwner={isOwner}
            currentPlanSlug={sub?.plan?.slug}
            hasActiveSubscription={Boolean(sub?.has_access)}
          />
        </div>
      </div>
    </div>
  );
}
