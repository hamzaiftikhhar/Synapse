import { PricingCards } from "@/components/marketing/pricing-cards";

export const metadata = { title: "Pricing" };

export default function PricingPage() {
  return (
    <div className="relative overflow-hidden bg-[#070714] text-white">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 70% 50% at 50% -10%, rgb(124 58 237 / 28%), transparent 58%), radial-gradient(ellipse 40% 35% at 90% 20%, rgb(88 28 180 / 18%), transparent 50%), radial-gradient(ellipse 35% 30% at 8% 70%, rgb(67 56 202 / 16%), transparent 50%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            "radial-gradient(rgb(255 255 255 / 55%) 0.6px, transparent 0.6px)",
          backgroundSize: "22px 22px",
        }}
      />

      <div className="relative mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-24">
        <p className="text-center text-sm text-white/50">
          Clinics’{" "}
          <span className="font-[family-name:var(--font-display)] text-lg italic text-[#c4b5fd]">
            best choice
          </span>
        </p>
        <h1 className="mt-3 text-center text-4xl font-semibold tracking-tight text-white sm:text-5xl">
          Pricing that scales with your practice
        </h1>
        <p className="mx-auto mt-4 max-w-lg text-center text-[15px] leading-relaxed text-white/55">
          Monthly plans for a clinical AI assistant — booking, insurance
          answers, and 24/7 patient chat. Starter, Professional, and
          Enterprise go live in days.
        </p>

        <div className="mt-16">
          <PricingCards />
        </div>
      </div>
    </div>
  );
}
