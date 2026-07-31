import Link from "next/link";
import { APP_NAME } from "@/constants";

const COLUMNS = [
  {
    title: "Product",
    links: [
      { href: "/features", label: "Features" },
      { href: "/pricing", label: "Pricing" },
      { href: "/solutions", label: "Solutions" },
      { href: "/developers", label: "Developers" },
    ],
  },
  {
    title: "Company",
    links: [
      { href: "/about", label: "About" },
      { href: "/blog", label: "Blog" },
      { href: "/contact", label: "Contact" },
    ],
  },
  {
    title: "Resources",
    links: [
      { href: "/login", label: "Sign in" },
      { href: "/register", label: "Request access" },
      { href: "/developers", label: "API docs" },
    ],
  },
];

export function MarketingFooter() {
  return (
    <footer className="section-navy">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="rounded-[6px] border border-white/10 bg-white/5 p-8 text-center sm:p-10">
          <h2 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
            Questions about fitting Synapse into{" "}
            <span className="text-gradient">your workflow</span>?
          </h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-white/60">
            Reach the team for implementation details, security reviews, or a
            clinic-specific walkthrough.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/contact"
              className="inline-flex h-9 items-center rounded-[6px] bg-primary px-4 text-sm font-medium text-primary-foreground"
            >
              Contact us
            </Link>
            <Link
              href="/pricing"
              className="inline-flex h-9 items-center rounded-[6px] border border-white/20 px-4 text-sm font-medium text-white hover:bg-white/5"
            >
              View Pricing
            </Link>
          </div>
        </div>

        <div className="mt-14 grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-sm font-semibold text-white">{APP_NAME}</p>
            <p className="mt-3 max-w-xs text-sm leading-relaxed text-white/50">
              The multi-tenant AI healthcare platform that helps clinics manage
              operations and engage patients through an intelligent chatbot.
            </p>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <p className="text-xs font-medium uppercase tracking-wider text-lavender">
                {col.title}
              </p>
              <ul className="mt-3 space-y-2">
                {col.links.map((l) => (
                  <li key={l.href + l.label}>
                    <Link
                      href={l.href}
                      className="text-sm text-white/60 hover:text-white"
                    >
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-2 border-t border-white/10 pt-6 text-xs text-white/40 sm:flex-row sm:items-center sm:justify-between">
          <p>© {new Date().getFullYear()} Synapse. All rights reserved.</p>
          <p>Built for clinic operators · Patients use the embed only</p>
        </div>
      </div>
    </footer>
  );
}
