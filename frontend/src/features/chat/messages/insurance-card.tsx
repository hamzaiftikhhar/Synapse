"use client";

import type { ChatActionHandler, InsuranceCardData } from "@/types/chat";

export function InsuranceCard({
  plan,
  onAction,
}: {
  plan: InsuranceCardData;
  onAction?: ChatActionHandler;
}) {
  return (
    <button
      type="button"
      onClick={() => onAction?.("select_insurance", plan)}
      className="w-full rounded-[6px] border border-border bg-white p-3 text-left transition-colors hover:border-primary/30 hover:bg-accent/40"
    >
      <p className="text-sm font-semibold text-navy">{plan.name}</p>
      {plan.plan ? <p className="text-xs text-muted-foreground">{plan.plan}</p> : null}
      {plan.notes ? <p className="mt-1 text-xs text-muted-foreground">{plan.notes}</p> : null}
    </button>
  );
}

export function InsuranceCards({
  plans,
  onAction,
}: {
  plans: InsuranceCardData[];
  onAction?: ChatActionHandler;
}) {
  return (
    <div className="grid gap-2">
      {plans.map((p, i) => (
        <InsuranceCard key={p.id || i} plan={p} onAction={onAction} />
      ))}
    </div>
  );
}
