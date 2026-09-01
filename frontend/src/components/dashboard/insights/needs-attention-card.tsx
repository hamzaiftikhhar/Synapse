"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { InsightCard } from "./insight-card";
import { cn } from "@/lib/utils";

type Severity = "red" | "amber";

const DOT_CLASS: Record<Severity, string> = {
  red: "bg-destructive",
  amber: "bg-warning",
};

function AttentionRow({
  severity,
  label,
  href,
}: {
  severity: Severity;
  label: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-2.5 rounded-[8px] px-1 py-2 text-[13px] transition-colors hover:bg-muted/60"
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", DOT_CLASS[severity])} />
      <span className="min-w-0 flex-1 truncate text-foreground">{label}</span>
      <span className="inline-flex shrink-0 items-center gap-0.5 text-[12px] font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
        Review
        <ArrowRight className="size-3" />
      </span>
    </Link>
  );
}

export function NeedsAttentionCard({
  escalatedConversations,
  pendingAppointments,
  className,
}: {
  escalatedConversations: number;
  pendingAppointments: number;
  className?: string;
}) {
  const items: Array<{ severity: Severity; label: string; href: string }> = [];
  if (escalatedConversations > 0) {
    items.push({
      severity: "red",
      label: `${escalatedConversations} escalated ${escalatedConversations === 1 ? "conversation" : "conversations"}`,
      href: "/dashboard/conversations",
    });
  }
  if (pendingAppointments > 0) {
    items.push({
      severity: "amber",
      label: `${pendingAppointments} ${pendingAppointments === 1 ? "appointment needs" : "appointments need"} confirmation`,
      href: "/dashboard/appointments",
    });
  }

  return (
    <InsightCard overflow="hidden" className={cn("p-5", className)}>
      <p className="text-[15px] font-medium text-foreground">Needs attention</p>
      {items.length === 0 ? (
        <div className="mt-3 flex items-start gap-2.5">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
          <div>
            <p className="text-[13px] font-medium text-foreground">You&apos;re all caught up</p>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              No conversations or appointments require attention.
            </p>
          </div>
        </div>
      ) : (
        <div className="mt-2 divide-y divide-border/60">
          {items.map((item) => (
            <AttentionRow key={item.label} {...item} />
          ))}
        </div>
      )}
    </InsightCard>
  );
}
