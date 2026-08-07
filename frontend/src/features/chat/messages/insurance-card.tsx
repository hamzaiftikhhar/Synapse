"use client";

import { useMemo, useState } from "react";
import { Check, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useSelectedInsurance } from "@/hooks/use-selected-insurance";
import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
import type { ChatActionHandler, InsuranceCardData } from "@/types/chat";

export function InsuranceCard({
  plan,
  onAction,
}: {
  plan: InsuranceCardData;
  onAction?: ChatActionHandler;
}) {
  const accepted = plan.is_accepted !== false;
  return (
    <button
      type="button"
      onClick={() => onAction?.("select_insurance", plan)}
      className={cn(
        "w-full rounded-lg border p-2.5 text-left transition-colors",
        accepted
          ? "border-border bg-white hover:border-primary/30 hover:bg-accent/40"
          : "border-destructive/20 bg-destructive/5 opacity-80"
      )}
    >
      <p className="text-sm font-medium text-foreground">{plan.name}</p>
      {plan.plan ? (
        <p className="text-xs text-muted-foreground">{plan.plan}</p>
      ) : null}
      {accepted ? (
        <span className="mt-1 inline-flex items-center gap-1 text-[10px] font-medium text-emerald-600">
          <Check className="size-3" /> Accepted
        </span>
      ) : null}
    </button>
  );
}

export function InsuranceCards({
  plans,
  onAction,
  clinicSlug,
}: {
  plans: InsuranceCardData[];
  onAction?: ChatActionHandler;
  clinicSlug?: string | null;
}) {
  const { selected, setSelected } = useSelectedInsurance(clinicSlug);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return plans;
    return plans.filter(
      (p) =>
        p.name.toLowerCase().includes(q) || (p.plan || "").toLowerCase().includes(q)
    );
  }, [plans, query]);

  // Selecting a plan from our own accepted-plans list is a state change, not
  // a new question — we already know the answer, so this never sends a chat
  // message (see chat-widget.tsx's now-removed select_insurance handler).
  const handleSelect = (plan: InsuranceCardData) => {
    setSelected(plan);
  };

  if (selected) {
    return (
      <ChatInlineCard className="space-y-2.5 rounded-[18px] border border-border/80 bg-white p-3 shadow-[0_2px_12px_rgb(11_14_46/0.06)]">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Selected Insurance
        </p>
        <div className="flex items-center justify-between gap-2 rounded-full border border-primary/25 bg-primary/[0.05] px-3 py-1.5">
          <p className="flex min-w-0 items-center gap-1.5 truncate text-xs font-medium text-foreground">
            <Check className="size-3.5 shrink-0 text-primary" />
            <span className="truncate">
              {selected.name}
              {selected.plan ? ` · ${selected.plan}` : ""}
            </span>
          </p>
          <Button
            type="button"
            variant="outline"
            size="xs"
            className="shrink-0 rounded-full"
            onClick={() => setSelected(null)}
          >
            Change
          </Button>
        </div>
        <Button
          type="button"
          size="sm"
          className="w-full rounded-lg"
          onClick={() => onAction?.("book_appointment", { insurance: selected.name })}
        >
          Continue to book
        </Button>
      </ChatInlineCard>
    );
  }

  return (
    <ChatInlineCard className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search insurance"
          className="h-8 rounded-lg pl-8 text-xs"
        />
      </div>
      <div className="max-h-48 space-y-1.5 overflow-y-auto">
        {filtered.map((p, i) => (
          <InsuranceCard
            key={p.id || i}
            plan={p}
            onAction={(_, data) => handleSelect(data as InsuranceCardData)}
          />
        ))}
        {!filtered.length ? (
          <p className="py-3 text-center text-xs text-muted-foreground">
            No matching plans
          </p>
        ) : null}
      </div>
    </ChatInlineCard>
  );
}
