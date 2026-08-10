"use client";

import type { ReactNode } from "react";
import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { APP_NAME } from "@/constants";
import { cn } from "@/lib/utils";
import { ONBOARDING_STAGES } from "./steps";

function StageProgress({ activeIndex }: { activeIndex: number }) {
  return (
    <div className="mb-8">
      <div className="flex gap-1.5">
        {ONBOARDING_STAGES.map((stage, i) => (
          <div
            key={stage.key}
            className={cn(
              "h-1.5 flex-1 rounded-full transition-colors",
              i <= activeIndex ? "bg-primary" : "bg-muted"
            )}
          />
        ))}
      </div>
      <div className="mt-2 hidden justify-between sm:flex">
        {ONBOARDING_STAGES.map((stage, i) => (
          <span
            key={stage.key}
            className={cn(
              "text-[11px] text-muted-foreground",
              i === activeIndex && "font-medium text-foreground"
            )}
          >
            {stage.label}
          </span>
        ))}
      </div>
      <p className="mt-2 text-[11px] font-medium text-foreground sm:hidden">
        {ONBOARDING_STAGES[activeIndex]?.label} · Stage {activeIndex + 1} of{" "}
        {ONBOARDING_STAGES.length}
      </p>
    </div>
  );
}

export function OnboardingShell({
  stageIndex,
  title,
  subtitle,
  onBack,
  formId,
  continueLabel = "Continue",
  continueDisabled,
  continueLoading,
  secondaryAction,
  hideFooter = false,
  children,
}: {
  stageIndex: number;
  title: string;
  subtitle?: string;
  onBack?: () => void;
  formId?: string;
  continueLabel?: string;
  continueDisabled?: boolean;
  continueLoading?: boolean;
  secondaryAction?: ReactNode;
  hideFooter?: boolean;
  children: ReactNode;
}) {
  return (
    <TooltipProvider>
      <div className="min-h-screen bg-background">
        <header className="border-b border-border">
          <div className="mx-auto flex h-14 max-w-2xl items-center justify-between px-6">
            <span className="text-sm font-semibold tracking-tight text-navy">
              {APP_NAME}
            </span>
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    aria-label="Get help with setup"
                    className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
                  />
                }
              >
                <HelpCircle className="size-4" />
              </TooltipTrigger>
              <TooltipContent>
                Questions? Your onboarding specialist can help — reach out any
                time.
              </TooltipContent>
            </Tooltip>
          </div>
        </header>

        <div className="mx-auto max-w-2xl px-6 py-10 pb-32 sm:py-14">
          <StageProgress activeIndex={stageIndex} />
          <h1 className="text-2xl font-semibold tracking-tight text-navy">
            {title}
          </h1>
          {subtitle ? (
            <p className="mt-2 max-w-lg text-sm text-muted-foreground">
              {subtitle}
            </p>
          ) : null}
          <div className="mt-8">{children}</div>
        </div>

        {!hideFooter ? (
          <footer className="fixed inset-x-0 bottom-0 border-t border-border bg-background/95 backdrop-blur">
            <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-6 py-4">
              <div>
                {onBack ? (
                  <Button type="button" variant="outline" onClick={onBack}>
                    Back
                  </Button>
                ) : (
                  <span />
                )}
              </div>
              <div className="flex items-center gap-3">
                {secondaryAction}
                <Button
                  type="submit"
                  form={formId}
                  disabled={continueDisabled || continueLoading}
                >
                  {continueLoading ? "Saving…" : continueLabel}
                </Button>
              </div>
            </div>
          </footer>
        ) : null}
      </div>
    </TooltipProvider>
  );
}
