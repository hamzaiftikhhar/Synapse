"use client";

import { cn } from "@/lib/utils";

/** Professional clinic-assistant mark — navy geometric face, not cartoon robot. */
export function RobotAvatar({
  size = "md",
  className,
  animate = false,
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
  animate?: boolean;
}) {
  const dim =
    size === "sm" ? "size-7" : size === "lg" ? "size-11" : "size-9";

  return (
    <div
      className={cn(
        "relative flex shrink-0 items-center justify-center rounded-[10px] bg-navy shadow-sm",
        dim,
        className
      )}
      aria-hidden
    >
      <svg
        viewBox="0 0 32 32"
        className={cn(
          "size-[62%]",
          animate && "animate-[robot-blink_4s_ease-in-out_infinite]"
        )}
      >
        <circle cx="11.5" cy="14" r="2" fill="#E8EEF9" className="robot-eye" />
        <circle cx="20.5" cy="14" r="2" fill="#E8EEF9" className="robot-eye" />
        <path
          d="M12 20.5c1.4 1.4 6.6 1.4 8 0"
          stroke="#A8B8D8"
          strokeWidth="1.6"
          fill="none"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}

export function RobotLauncherIcon({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex size-full items-center justify-center rounded-[10px] bg-navy",
        className
      )}
    >
      <svg viewBox="0 0 32 32" className="size-6" aria-hidden>
        <circle cx="11.5" cy="14" r="2.2" fill="white" fillOpacity="0.95" />
        <circle cx="20.5" cy="14" r="2.2" fill="white" fillOpacity="0.95" />
        <path
          d="M12 20.5c1.4 1.4 6.6 1.4 8 0"
          stroke="white"
          strokeOpacity="0.75"
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
