import Link from "next/link";

type Props = {
  href?: string;
  headline?: string;
  subheadline?: string;
  ctaLabel?: string;
};

export function DemoCtaBanner({
  href = "/contact",
  headline = "Let's talk!",
  subheadline = "Schedule a call with our experts",
  ctaLabel = "Book a Demo",
}: Props) {
  return (
    <section className="px-4 sm:px-6">
      <div className="relative mx-auto flex max-w-6xl flex-col items-center gap-8 overflow-hidden rounded-[20px] bg-[linear-gradient(105deg,#6d28d9_0%,#7c3aed_32%,#818cf8_72%,#a5b4fc_100%)] px-8 py-10 text-center shadow-[0_20px_50px_-28px_rgba(91,33,182,0.55)] sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-10 sm:py-8 sm:text-left">
        <div className="relative z-10 max-w-xs shrink-0">
          <h2 className="font-[family-name:var(--font-display)] text-4xl font-semibold italic tracking-tight text-white sm:text-[2.75rem] sm:leading-none">
            {headline}
          </h2>
          <p className="mt-2 text-sm text-white/90 sm:text-[15px]">
            {subheadline}
          </p>
        </div>

        <div className="relative z-10 flex h-[140px] w-[180px] shrink-0 items-center justify-center sm:h-[160px] sm:w-[210px]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/marketing/cta-calendar.svg"
            alt=""
            width={226}
            height={182}
            className="h-full w-full object-contain drop-shadow-[0_18px_30px_rgba(30,27,75,0.28)]"
          />
        </div>

        <div className="relative z-10 shrink-0">
          <Link
            href={href}
            className="inline-flex h-11 items-center gap-2 rounded-[8px] bg-[#312e81] px-5 text-sm font-medium text-white transition-colors hover:bg-[#1e1b4b]"
          >
            {ctaLabel}
            <span aria-hidden="true">→</span>
          </Link>
        </div>
      </div>
    </section>
  );
}
