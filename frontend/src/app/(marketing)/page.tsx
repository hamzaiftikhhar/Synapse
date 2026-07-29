import Link from "next/link";
import {
  Bot,
  CalendarCheck2,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  BookOpen,
} from "lucide-react";
import { ChatWidget } from "@/features/chat";

const STATS = [
  { value: "98%", label: "Patient question resolution in demo clinics" },
  { value: "<2s", label: "Typical chatbot first response target" },
  { value: "1", label: "Unified platform for ops + patient chat" },
  { value: "HIPAA", label: "Architecture designed for regulated care" },
];

const FEATURES = [
  {
    num: "01",
    title: "Patient Chatbot",
    items: [
      ["Intent routing", "Book, find doctors, insurance, hours, FAQ."],
      ["Rich UI messages", "Cards, slots, calendars — not text-only."],
      ["Knowledge answers", "Grounded replies from clinic PDFs."],
      ["Embed anywhere", "Widget mode for clinic websites."],
    ],
  },
  {
    num: "02",
    title: "Clinic Operations",
    items: [
      ["Doctors & services", "Keep provider catalogs accurate."],
      ["Appointments", "Track chatbot and admin bookings."],
      ["Patients", "Phone-verified identities for the widget."],
      ["Multi-tenant", "Every clinic isolated by JWT scope."],
    ],
  },
  {
    num: "03",
    title: "Knowledge & AI",
    items: [
      ["PDF ingestion", "Extract → chunk → embed → index."],
      ["SQL-aware replies", "Live clinic data when questions need it."],
      ["Safety rails", "Clinical disclaimers when required."],
      ["Staff QA console", "Test routes before going live."],
    ],
  },
  {
    num: "04",
    title: "Scheduling Context",
    items: [
      ["Availability flows", "Date and time-slot message types."],
      ["Confirmation cards", "Clear booking summaries for patients."],
      ["Source tracking", "Know what came from chatbot vs admin."],
      ["Status control", "Confirm, cancel, complete in portal."],
    ],
  },
  {
    num: "05",
    title: "Insurance & Services",
    items: [
      ["Service catalog", "Duration, pricing, descriptions."],
      ["Insurance cards", "Accepted plans surfaced in chat."],
      ["Doctor matching", "Specialty and service associations."],
      ["Consistent answers", "Same truth in portal and widget."],
    ],
  },
  {
    num: "06",
    title: "Security & Tenancy",
    items: [
      ["Staff JWT", "Clinic-scoped portal authentication."],
      ["Patient OTP JWT", "Short-lived widget sessions."],
      ["Role model", "SUPER_ADMIN, CLINIC_ADMIN, STAFF."],
      ["API-first", "Django Ninja + OpenAPI contracts."],
    ],
  },
];

const STEPS = [
  {
    title: "Configure your clinic",
    body: "Add doctors, services, hours context, and insurance details in the portal.",
  },
  {
    title: "Upload knowledge",
    body: "Index PDFs so the chatbot can answer policy and prep questions accurately.",
  },
  {
    title: "Embed the widget",
    body: "Drop Synapse on your clinic website. Patients never access the dashboard.",
  },
];

export default function LandingPage() {
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="glow-purple pointer-events-none absolute inset-0" />
        <div className="relative mx-auto max-w-6xl px-4 pb-16 pt-16 sm:px-6 sm:pb-24 sm:pt-24">
          <p className="text-center text-xs font-medium uppercase tracking-[0.2em] text-primary">
            AI Healthcare Platform
          </p>
          <h1 className="mx-auto mt-4 max-w-3xl text-center text-4xl font-semibold tracking-tight text-navy sm:text-5xl sm:leading-[1.1]">
            The leading software for{" "}
            <span className="text-gradient">modern clinics</span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-center text-base leading-relaxed text-muted-foreground sm:text-lg">
            Synapse helps clinic teams manage operations while an intelligent
            patient chatbot handles booking questions, insurance, doctors, and
            knowledge — embedded on your website.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/contact"
              className="inline-flex h-10 items-center rounded-[6px] bg-navy px-5 text-sm font-medium text-white hover:bg-navy/90"
            >
              Book a Demo
            </Link>
            <Link
              href="/features"
              className="inline-flex h-10 items-center rounded-[6px] border border-border bg-white px-5 text-sm font-medium text-navy hover:bg-muted"
            >
              Explore features
            </Link>
          </div>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-4 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="size-3.5 text-primary" /> HIPAA-ready design
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Sparkles className="size-3.5 text-primary" /> Multi-tenant SaaS
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Bot className="size-3.5 text-primary" /> Embeddable chatbot
            </span>
          </div>

          {/* Product mock */}
          <div className="relative mx-auto mt-14 max-w-5xl">
            <div className="overflow-hidden rounded-[6px] border border-border bg-white shadow-[0_30px_80px_-40px_rgba(91,33,182,0.45)]">
              <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-4 py-2.5">
                <span className="size-2.5 rounded-full bg-[#ff5f57]" />
                <span className="size-2.5 rounded-full bg-[#febc2e]" />
                <span className="size-2.5 rounded-full bg-[#28c840]" />
                <span className="ml-3 text-xs text-muted-foreground">
                  app.synapse.health / dashboard
                </span>
              </div>
              <div className="grid lg:grid-cols-[220px_1fr]">
                <div className="hidden border-r border-border bg-[#fafaff] p-4 lg:block">
                  <p className="text-xs font-semibold text-navy">Synapse</p>
                  <div className="mt-4 space-y-1.5 text-xs text-muted-foreground">
                    {[
                      "Dashboard",
                      "Doctors",
                      "Services",
                      "Appointments",
                      "Knowledge",
                      "Chatbot",
                    ].map((item, i) => (
                      <div
                        key={item}
                        className={`rounded-[6px] px-2 py-1.5 ${
                          i === 5 ? "bg-accent font-medium text-accent-foreground" : ""
                        }`}
                      >
                        {item}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-6">
                  <div className="space-y-3">
                    <div className="rounded-[6px] border border-border p-4">
                      <p className="text-xs text-muted-foreground">Appointments today</p>
                      <p className="mt-1 text-2xl font-semibold text-navy">24</p>
                    </div>
                    <div className="rounded-[6px] border border-border p-4">
                      <p className="text-xs text-muted-foreground">Indexed documents</p>
                      <p className="mt-1 text-2xl font-semibold text-navy">12</p>
                    </div>
                    <div className="rounded-[6px] border border-border p-4">
                      <div className="flex items-center gap-2 text-xs text-primary">
                        <CalendarCheck2 className="size-3.5" /> Claim accepted
                      </div>
                      <p className="mt-2 text-lg font-semibold text-navy">Session synced</p>
                      <p className="text-xs text-muted-foreground">Chatbot booking → portal</p>
                    </div>
                  </div>
                  <div className="h-[420px] min-h-[320px]">
                    <ChatWidget
                      mode="embedded"
                      demoMode
                      clinicName="Acme Cardiology"
                      className="h-full w-full max-w-none shadow-none"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Logo / trust */}
      <section className="border-y border-border bg-muted/30 py-10">
        <div className="mx-auto max-w-6xl px-4 text-center sm:px-6">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Built for clinics that outgrow phone trees and static FAQs
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-sm font-medium text-muted-foreground/80">
            {[
              "Cardiology groups",
              "Multi-location practices",
              "Specialty clinics",
              "Growing primary care",
            ].map((t) => (
              <span key={t}>{t}</span>
            ))}
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="py-16 sm:py-20">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 sm:grid-cols-2 sm:px-6 lg:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label} className="text-center lg:text-left">
              <p className="text-3xl font-semibold tracking-tight text-navy">
                {s.value}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Benefits strip */}
      <section className="pb-8">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="grid gap-6 rounded-[6px] border border-border bg-white p-8 sm:grid-cols-3">
            {[
              {
                icon: Bot,
                title: "Patients chat. Staff operate.",
                body: "Patients never log into the dashboard — only the embed.",
              },
              {
                icon: Stethoscope,
                title: "One source of truth",
                body: "Doctors, services, and knowledge power both portal and chatbot.",
              },
              {
                icon: BookOpen,
                title: "Knowledge that answers",
                body: "Upload PDFs once. Let RAG handle repetitive questions.",
              },
            ].map((b) => (
              <div key={b.title}>
                <b.icon className="size-5 text-primary" />
                <h3 className="mt-3 text-sm font-semibold text-navy">{b.title}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground">{b.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Dark feature grid — Raven style */}
      <section className="relative mt-12 overflow-hidden section-navy py-20 sm:py-24">
        <div className="glow-navy pointer-events-none absolute inset-0" />
        <div className="relative mx-auto max-w-6xl px-4 sm:px-6">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.2em] text-lavender">
                — The Platform
              </p>
              <h2 className="mt-3 max-w-xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                Modern features that drive{" "}
                <span className="text-gradient">healthcare</span> providers
              </h2>
            </div>
            <p className="max-w-sm text-sm leading-relaxed text-white/55">
              Everything your team needs to run clinic operations and patient
              conversations in one system.
            </p>
          </div>

          <div className="mt-14 grid border-t border-white/10 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div
                key={f.num}
                className="border-b border-white/10 p-6 sm:border-r sm:odd:[&:nth-child(2n)]:border-r-0 lg:odd:[&:nth-child(2n)]:border-r lg:[&:nth-child(3n)]:border-r-0"
              >
                <p className="text-xs font-medium text-lavender">{f.num}</p>
                <h3 className="mt-3 text-lg font-semibold text-white">{f.title}</h3>
                <ul className="mt-4 space-y-2.5">
                  {f.items.map(([label, desc]) => (
                    <li key={label} className="text-sm leading-snug">
                      <span className="font-medium text-white">{label}: </span>
                      <span className="text-white/50">{desc}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-20 sm:py-24">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-primary">
            How it works
          </p>
          <h2 className="mt-3 max-w-xl text-3xl font-semibold tracking-tight text-navy">
            Live in three calm steps
          </h2>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <div
                key={s.title}
                className="rounded-[6px] border border-border p-6"
              >
                <p className="text-xs font-medium text-lavender">
                  {String(i + 1).padStart(2, "0")}
                </p>
                <h3 className="mt-3 text-base font-semibold text-navy">{s.title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing teaser */}
      <section className="border-t border-border bg-muted/20 py-20">
        <div className="mx-auto max-w-6xl px-4 text-center sm:px-6">
          <h2 className="text-3xl font-semibold tracking-tight text-navy">
            Simple pricing for growing clinics
          </h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-muted-foreground">
            Start with a single location. Add capacity as conversation volume and
            locations grow.
          </p>
          <div className="mx-auto mt-10 grid max-w-4xl gap-4 md:grid-cols-3">
            {[
              {
                name: "Starter",
                price: "$299",
                desc: "1 clinic · chatbot · core ops",
              },
              {
                name: "Growth",
                price: "$699",
                desc: "Higher volume · knowledge · QA tools",
                featured: true,
              },
              {
                name: "Enterprise",
                price: "Custom",
                desc: "Multi-location · SSO roadmap · support",
              },
            ].map((p) => (
              <div
                key={p.name}
                className={`rounded-[6px] border p-6 text-left ${
                  p.featured
                    ? "border-primary/40 bg-white shadow-sm"
                    : "border-border bg-white"
                }`}
              >
                <p className="text-sm font-medium text-navy">{p.name}</p>
                <p className="mt-3 text-3xl font-semibold text-navy">
                  {p.price}
                  {p.price.startsWith("$") ? (
                    <span className="text-sm font-normal text-muted-foreground">
                      /mo
                    </span>
                  ) : null}
                </p>
                <p className="mt-2 text-sm text-muted-foreground">{p.desc}</p>
              </div>
            ))}
          </div>
          <Link
            href="/pricing"
            className="mt-8 inline-flex text-sm font-medium text-primary hover:underline"
          >
            See full pricing →
          </Link>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-20 sm:py-24">
        <div className="mx-auto max-w-3xl px-4 sm:px-6">
          <h2 className="text-center text-3xl font-semibold tracking-tight text-navy">
            Frequently asked <span className="text-gradient">questions</span>
          </h2>
          <div className="mt-10 divide-y divide-border border-y border-border">
            {[
              {
                q: "Do patients log into Synapse?",
                a: "No. Patients only use the chatbot widget on your clinic website. Staff use the portal.",
              },
              {
                q: "What APIs power the product?",
                a: "Django Ninja endpoints for staff JWT auth, patient OTP, chat, doctors, services, appointments, patients, and knowledge documents.",
              },
              {
                q: "Can the chatbot show more than text?",
                a: "Yes. Synapse ships message components for cards, doctors, insurance, services, calendars, time slots, forms, and confirmations.",
              },
              {
                q: "Is registration self-serve today?",
                a: "Staff login exists today. Self-serve register / reset / verify flows are stubbed until those backend endpoints ship.",
              },
            ].map((item) => (
              <details key={item.q} className="group py-4">
                <summary className="cursor-pointer list-none text-sm font-medium text-navy marker:content-none">
                  <div className="flex items-center justify-between gap-4">
                    {item.q}
                    <span className="text-muted-foreground group-open:hidden">+</span>
                    <span className="hidden text-muted-foreground group-open:inline">−</span>
                  </div>
                </summary>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {item.a}
                </p>
              </details>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
