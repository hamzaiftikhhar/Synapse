import Link from "next/link";

export const metadata = { title: "Pricing" };

const PLANS = [
  {
    name: "Starter",
    price: "$299",
    featured: false,
    items: ["1 clinic tenant", "Staff portal", "Chatbot embed", "Core CRUD APIs"],
  },
  {
    name: "Growth",
    price: "$699",
    featured: true,
    items: ["Higher chat volume", "Knowledge base", "Staff QA console", "Priority onboarding"],
  },
  {
    name: "Enterprise",
    price: "Custom",
    featured: false,
    items: ["Multi-location", "Custom SLAs", "Security review", "Dedicated success"],
  },
];

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <h1 className="text-center text-4xl font-semibold tracking-tight text-navy">
        Pricing that scales with your clinics
      </h1>
      <p className="mx-auto mt-3 max-w-lg text-center text-muted-foreground">
        Transparent monthly plans. Billing APIs are forthcoming — contact us to start.
      </p>
      <div className="mt-12 grid gap-4 md:grid-cols-3">
        {PLANS.map((p) => (
          <div
            key={p.name}
            className={`rounded-[6px] border bg-white p-6 ${
              p.featured ? "border-primary/40 shadow-sm" : "border-border"
            }`}
          >
            <p className="text-sm font-medium text-navy">{p.name}</p>
            <p className="mt-3 text-3xl font-semibold text-navy">
              {p.price}
              {p.price.startsWith("$") ? (
                <span className="text-sm font-normal text-muted-foreground">/mo</span>
              ) : null}
            </p>
            <ul className="mt-5 space-y-2 text-sm text-muted-foreground">
              {p.items.map((i) => (
                <li key={i}>· {i}</li>
              ))}
            </ul>
            <Link
              href="/contact"
              className="mt-6 inline-flex h-9 w-full items-center justify-center rounded-[6px] bg-navy text-sm font-medium text-white"
            >
              Talk to sales
            </Link>
          </div>
        ))}
      </div>
      <p className="mt-8 text-center text-xs text-muted-foreground">
        TODO: Backend endpoint required for self-serve billing checkout.
      </p>
    </div>
  );
}
