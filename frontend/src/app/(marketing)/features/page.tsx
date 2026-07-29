import Link from "next/link";

export const metadata = { title: "Features" };

const GROUPS = [
  {
    title: "Patient chatbot",
    body: "Rich message types, main menu, suggested questions, and staff QA console.",
  },
  {
    title: "Clinic operations",
    body: "Doctors, services, patients, appointments — wired to live Django APIs.",
  },
  {
    title: "Knowledge base",
    body: "PDF upload, chunking, embeddings, and reindex for grounded answers.",
  },
  {
    title: "Dual auth",
    body: "Staff JWT for the portal. Patient OTP JWT for the embed — never mixed.",
  },
];

export default function FeaturesPage() {
  return (
    <div className="relative overflow-hidden">
      <div className="glow-purple pointer-events-none absolute inset-0" />
      <div className="relative mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-[0.2em] text-primary">Features</p>
        <h1 className="mt-3 max-w-2xl text-4xl font-semibold tracking-tight text-navy">
          Everything your clinic needs to run ops and patient chat
        </h1>
        <p className="mt-4 max-w-xl text-muted-foreground">
          Synapse combines a multi-tenant clinic portal with an embeddable AI chatbot designed for healthcare workflows.
        </p>
        <div className="mt-12 grid gap-4 sm:grid-cols-2">
          {GROUPS.map((g) => (
            <div key={g.title} className="rounded-[6px] border border-border bg-white p-6">
              <h2 className="text-base font-semibold text-navy">{g.title}</h2>
              <p className="mt-2 text-sm text-muted-foreground">{g.body}</p>
            </div>
          ))}
        </div>
        <Link href="/contact" className="mt-10 inline-flex text-sm font-medium text-primary hover:underline">
          Book a demo →
        </Link>
      </div>
    </div>
  );
}
