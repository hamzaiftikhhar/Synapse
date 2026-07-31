"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type FaqItem = {
  question: string;
  answer: string;
};

type Props = {
  title?: string;
  items: FaqItem[];
};

export function MarketingFaq({
  title = "Frequently Asked Questions",
  items,
}: Props) {
  const [openIndex, setOpenIndex] = useState(0);

  return (
    <section className="section-navy relative overflow-hidden py-20 sm:py-24">
      <div className="glow-navy pointer-events-none absolute inset-0" />
      <div className="relative mx-auto grid max-w-6xl gap-12 px-4 sm:px-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(240px,0.7fr)] lg:items-start lg:gap-16">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
            {title}
          </h2>
          <div className="mt-8 divide-y divide-white/15 border-y border-white/15">
            {items.map((item, index) => {
              const open = openIndex === index;
              return (
                <div key={item.question}>
                  <button
                    type="button"
                    className="flex w-full items-start justify-between gap-4 py-5 text-left"
                    aria-expanded={open}
                    onClick={() =>
                      setOpenIndex((prev) => (prev === index ? -1 : index))
                    }
                  >
                    <span className="text-[15px] font-medium leading-snug text-white">
                      {item.question}
                    </span>
                    <ChevronDown
                      className={cn(
                        "mt-0.5 size-4 shrink-0 text-white/70 transition-transform duration-200",
                        open && "rotate-180"
                      )}
                    />
                  </button>
                  <div
                    className={cn(
                      "grid transition-[grid-template-rows] duration-200 ease-out",
                      open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                    )}
                  >
                    <div className="overflow-hidden">
                      <p className="pb-5 pr-8 text-sm leading-relaxed text-white/60">
                        {item.answer}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="pointer-events-none mx-auto w-full max-w-[280px] lg:max-w-[320px]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/marketing/faq-messages.svg"
            alt=""
            width={338}
            height={345}
            className="mx-auto h-auto w-full drop-shadow-[0_24px_40px_rgba(0,0,0,0.35)]"
          />
        </div>
      </div>
    </section>
  );
}
