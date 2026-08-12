"use client";

import Link from "next/link";
import {
  Activity,
  Building2,
  CalendarCheck2,
  MessageCircle,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Feature = { label: string; value: string; Icon: typeof MessageCircle };

type Plan = {
  slug: string;
  name: string;
  tagline: string;
  price: string;
  period?: string;
  featured?: boolean;
  badge?: string;
  rank: string;
  cta: string;
  href: string;
  features: Feature[];
};

const PLANS: Plan[] = [
  {
    slug: "starter",
    name: "Starter",
    tagline: "Turn visitors into patients.",
    price: "$29",
    period: "/ month",
    rank: "Growing practices",
    cta: "Start with Starter",
    href: "/get-started?plan=starter",
    features: [
      { label: "Conversations", value: "1,000 / month", Icon: MessageCircle },
      { label: "Front desk", value: "24/7 patient assistant", Icon: Sparkles },
      { label: "Booking", value: "New appointments", Icon: CalendarCheck2 },
      { label: "Guidance", value: "Insurance & services", Icon: ShieldCheck },
    ],
  },
  {
    slug: "growth",
    name: "Professional",
    tagline: "Automate your front desk.",
    price: "$49",
    period: "/ month",
    featured: true,
    badge: "Practices’ pick",
    rank: "Most chosen",
    cta: "Choose Professional",
    href: "/get-started?plan=growth",
    features: [
      { label: "Conversations", value: "5,000 / month", Icon: MessageCircle },
      { label: "Booking", value: "Book, reschedule, cancel", Icon: CalendarCheck2 },
      { label: "Identity", value: "Patient verification", Icon: ShieldCheck },
      { label: "Matching", value: "Doctors & availability", Icon: Activity },
      { label: "Insights", value: "Analytics included", Icon: Sparkles },
    ],
  },
  {
    slug: "enterprise",
    name: "Enterprise",
    tagline: "AI infrastructure for modern healthcare.",
    price: "Custom",
    rank: "Multi-location",
    cta: "Talk to us",
    href: "/contact?interest=enterprise",
    features: [
      { label: "Conversations", value: "Unlimited", Icon: MessageCircle },
      { label: "Locations", value: "Multi-clinic management", Icon: Building2 },
      { label: "Workflows", value: "Advanced appointments", Icon: CalendarCheck2 },
      { label: "Knowledge", value: "Custom clinic AI", Icon: Sparkles },
      { label: "Support", value: "Priority onboarding", Icon: ShieldCheck },
    ],
  },
];

function PlanOrb({ featured }: { featured?: boolean }) {
  return (
    <span className={cn("plan-orb", featured && "plan-orb-featured")} aria-hidden>
      <span className="plan-orb-core" />
      <span className="plan-orb-shine" />
    </span>
  );
}

function PlanCard({ plan }: { plan: Plan }) {
  return (
    <article
      className={cn(
        "glass-plan flex flex-col",
        plan.featured && "glass-plan-featured md:-mt-6 md:mb-[-1.5rem]"
      )}
    >
      {plan.badge ? <p className="glass-plan-badge">{plan.badge}</p> : null}

      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium tracking-wide text-white/55">
            {plan.name}
          </p>
          <p className="mt-3 font-[family-name:var(--font-display)] text-[2.35rem] leading-none tracking-tight text-white">
            {plan.price}
            {plan.period ? (
              <span className="ml-1 align-middle font-sans text-sm font-normal text-white/45">
                {plan.period}
              </span>
            ) : null}
          </p>
        </div>
        <PlanOrb featured={plan.featured} />
      </div>

      <p className="mt-4 text-[15px] leading-snug text-white/80">{plan.tagline}</p>

      <ul className="mt-6 flex-1 divide-y divide-white/[0.06]">
        {plan.features.map((f) => (
          <li key={f.label} className="flex items-start gap-3 py-3 first:pt-0">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/[0.06] text-violet-200/80">
              <f.Icon className="size-3.5" strokeWidth={1.75} />
            </span>
            <span>
              <span className="block text-[11px] uppercase tracking-[0.14em] text-white/40">
                {f.label}
              </span>
              <span className="mt-0.5 block text-sm text-white/90">{f.value}</span>
            </span>
          </li>
        ))}
      </ul>

      <Link
        href={plan.href}
        className={cn(
          "mt-6 inline-flex h-11 w-full items-center justify-center rounded-full text-sm font-medium transition-[transform,box-shadow,background-color] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/80 focus-visible:ring-offset-2 focus-visible:ring-offset-[#070714]",
          plan.featured
            ? "bg-[#8b5cff] text-white shadow-[0_0_28px_rgb(139_92_255/0.45)] hover:bg-[#9b72ff]"
            : "bg-white/[0.08] text-white hover:bg-white/[0.14]"
        )}
      >
        {plan.cta}
      </Link>
      <Link
        href="/features"
        className="mt-2 inline-flex h-10 w-full items-center justify-center rounded-full bg-transparent text-sm text-white/50 transition-colors hover:text-white/80"
      >
        View capabilities
      </Link>
    </article>
  );
}

export function PricingCards() {
  return (
    <div className="pricing-glass">
      <div className="relative mx-auto grid max-w-5xl items-end gap-5 md:grid-cols-3">
        {PLANS.map((plan) => (
          <div key={plan.slug} className="flex flex-col items-center">
            <PlanCard plan={plan} />
            <p
              className={cn(
                "mt-4 rounded-full border px-3 py-1 text-[11px] tracking-[0.16em] uppercase",
                plan.featured
                  ? "border-violet-400/40 bg-violet-500/15 text-violet-200 shadow-[0_0_18px_rgb(139_92_255/0.25)]"
                  : "border-white/10 bg-white/[0.04] text-white/40"
              )}
            >
              {plan.rank}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
