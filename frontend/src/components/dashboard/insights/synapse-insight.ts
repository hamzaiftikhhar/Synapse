import type { AnalyticsNamedCount, AnalyticsOverview } from "@/types/api";

export type SynapseInsight = {
  text: string;
  href: string;
  hrefLabel: string;
};

/**
 * Deterministic, rule-based "Synapse insight" — computed entirely from data
 * the dashboard already fetches (no extra request, no LLM call). Picks the
 * single most decision-relevant fact from the current analytics window,
 * priority-ordered: a meaningful volume shift beats a steady-state summary.
 */
export function computeSynapseInsight(data: AnalyticsOverview): SynapseInsight {
  const { summary, appointments_by_specialty: specialties, ops } = data;
  const conversations = summary.conversations;
  const escalated = ops.inbox.escalated;
  const changePct = summary.appointments_change_pct;

  if (changePct != null && Math.abs(changePct) >= 15 && summary.appointments > 0) {
    const direction = changePct >= 0 ? "increased" : "decreased";
    const lead = specialtyLead(specialties);
    const text = lead
      ? `Appointment volume ${direction} ${Math.abs(Math.round(changePct))}% compared with the previous period. ${lead}`
      : `Appointment volume ${direction} ${Math.abs(Math.round(changePct))}% compared with the previous period.`;
    return { text, href: "/dashboard/analytics", hrefLabel: "View analytics" };
  }

  const lead = specialtyLead(specialties);
  if (lead) {
    return { text: lead, href: "/dashboard/analytics", hrefLabel: "View analytics" };
  }

  if (conversations > 0) {
    const text =
      escalated > 0
        ? `Synapse handled ${conversations} ${plural(conversations, "conversation")} this period, with ${escalated} escalated to staff.`
        : `Synapse handled all ${conversations} ${plural(conversations, "conversation")} this period without needing to escalate to staff.`;
    return { text, href: "/dashboard/conversations", hrefLabel: "View conversations" };
  }

  return {
    text: `${summary.appointments} ${plural(summary.appointments, "appointment")} and ${conversations} ${plural(conversations, "conversation")} this period — steady activity, no unusual shifts.`,
    href: "/dashboard/analytics",
    hrefLabel: "View analytics",
  };
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`;
}

function specialtyLead(specialties: AnalyticsNamedCount[] | undefined): string | null {
  if (!Array.isArray(specialties) || specialties.length === 0) return null;
  const total = specialties.reduce((sum, s) => sum + (s.count || 0), 0);
  if (total <= 0) return null;
  const top = [...specialties].sort((a, b) => b.count - a.count).slice(0, 2);
  const share = top.reduce((sum, s) => sum + s.count, 0) / total;
  if (share < 0.4) return null;
  const pct = Math.round(share * 100);
  const names = top.map((s) => s.label).join(" and ");
  return `${names} account${top.length === 1 ? "s" : ""} for ${pct}% of bookings this period.`;
}
