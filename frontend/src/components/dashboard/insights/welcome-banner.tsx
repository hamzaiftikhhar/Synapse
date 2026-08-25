import Link from "next/link";
import { InsightCard } from "./insight-card";
import { ClinicianIllustration } from "./illustrations";

export function WelcomeBanner({
  firstName,
  clinicName,
}: {
  firstName?: string;
  clinicName?: string;
}) {
  const name = firstName?.trim() || "there";
  const clinic = clinicName?.trim() || "your clinic";

  return (
    <InsightCard tone="wash" overflow="visible" className="mb-5">
      <div className="relative flex min-h-[148px] items-stretch gap-6 px-6 py-5 md:px-7">
        <div className="pointer-events-none absolute -right-2 -top-8 hidden h-[210px] w-[210px] md:block lg:right-6">
          <ClinicianIllustration className="h-full w-full" />
        </div>
        <div className="relative z-[1] max-w-[38rem] py-2 pr-4 md:pr-[13rem]">
          <p className="font-[family-name:var(--font-display)] text-[1.75rem] leading-tight text-[var(--insight-ink-deep)] italic">
            Welcome, {name}
          </p>
          <p className="mt-2 max-w-md text-[13px] leading-relaxed text-[var(--insight-ink)]/75">
            {clinic} at a glance — visits on the books, what the front-desk
            assistant handled, and what still needs a person.
          </p>
          <Link
            href="/dashboard/chatbot"
            className="mt-4 inline-flex h-8 items-center rounded-[8px] bg-[var(--insight-ink)] px-3 text-[13px] font-medium text-white hover:bg-[var(--insight-ink-deep)]"
          >
            Open chatbot QA
          </Link>
        </div>
      </div>
    </InsightCard>
  );
}
