"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { APP_NAME } from "@/constants";
import { getApiErrorMessage } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import { cn } from "@/lib/utils";
import { ONBOARDING_STAGES } from "./steps";

function StageProgress({ activeIndex }: { activeIndex: number }) {
  return (
    <div className="mb-8">
      <div className="grid grid-cols-8 gap-1.5">
        {ONBOARDING_STAGES.map((stage, i) => (
          <div key={stage.key} className="min-w-0">
            <div
              className={cn(
                "h-1.5 w-full rounded-full transition-colors",
                i <= activeIndex ? "bg-primary" : "bg-muted"
              )}
            />
            <span
              className={cn(
                "mt-2 hidden text-center text-[11px] leading-tight sm:block",
                i === activeIndex
                  ? "font-medium text-foreground"
                  : "text-muted-foreground"
              )}
            >
              {stage.label}
            </span>
          </div>
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
  wide = false,
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
  wide?: boolean;
  children: ReactNode;
}) {
  const frame = cn("mx-auto px-6", wide ? "max-w-5xl" : "max-w-3xl");
  const { user, clinic, canExitClinic, exitClinic } = useAuth();
  const router = useRouter();
  const [exiting, setExiting] = useState(false);
  const impersonating =
    user?.role === "SUPER_ADMIN" && Boolean(clinic) && canExitClinic;

  useEffect(() => {
    document.body.classList.add("theme-instrument", "theme-light");
    return () => {
      document.body.classList.remove("theme-instrument", "theme-light");
    };
  }, []);

  async function handleExit() {
    setExiting(true);
    try {
      await exitClinic();
      toast.success("Returned to platform");
      router.push("/dashboard/platform/clinics");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setExiting(false);
    }
  }

  return (
    <TooltipProvider>
      <div className="theme-instrument theme-light flex h-dvh flex-col overflow-hidden bg-background">
        {impersonating ? (
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-warning/25 bg-warning/10 px-4 py-2.5 sm:px-6">
            <p className="text-sm text-foreground">
              <span className="font-semibold">{clinic?.name}</span>
              <span className="text-muted-foreground">
                {" "}
                · Super Admin testing setup
              </span>
            </p>
            <div className="flex shrink-0 gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => router.push("/dashboard/platform/clinics")}
              >
                Switch clinic
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={exiting}
                onClick={() => void handleExit()}
              >
                {exiting ? "Exiting…" : "Exit clinic"}
              </Button>
            </div>
          </div>
        ) : null}
        <header className="shrink-0 border-b border-border">
          <div className={cn("flex h-14 items-center justify-between", frame)}>
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

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className={cn("py-10 sm:py-14", frame)}>
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
        </div>

        {!hideFooter ? (
          <footer className="shrink-0 border-t border-border bg-background/95 backdrop-blur">
            <div className={cn("flex items-center justify-between gap-3 py-4", frame)}>
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
