"use client";

import { cn } from "@/lib/utils";

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
        "relative shrink-0 rounded-[8px] bg-gradient-to-br from-[#7c3aed] via-[#6366f1] to-[#4f46e5] p-[2px] shadow-sm",
        dim,
        className
      )}
    >
      <div className="flex size-full items-center justify-center rounded-[6px] bg-gradient-to-b from-[#f5f3ff] to-[#ede9fe]">
        <svg
          viewBox="0 0 32 32"
          className={cn(
            "size-[70%]",
            animate && "animate-[robot-blink_4s_ease-in-out_infinite]"
          )}
          aria-hidden
        >
          <rect x="8" y="10" width="16" height="14" rx="4" fill="#5b21b6" />
          <circle cx="13" cy="16" r="2.2" fill="#faf5ff" className="robot-eye" />
          <circle cx="19" cy="16" r="2.2" fill="#faf5ff" className="robot-eye" />
          <path
            d="M13 21 Q16 23 19 21"
            stroke="#c4b5fd"
            strokeWidth="1.5"
            fill="none"
            strokeLinecap="round"
          />
          <rect x="14" y="5" width="4" height="5" rx="1" fill="#7c3aed" />
          <circle cx="16" cy="4" r="2" fill="#a78bfa" />
        </svg>
      </div>
    </div>
  );
}

export function RobotLauncherIcon({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex size-full items-center justify-center rounded-[6px] bg-gradient-to-br from-[#7c3aed] to-[#4f46e5]",
        className
      )}
    >
      <svg viewBox="0 0 32 32" className="size-6" aria-hidden>
        <rect x="8" y="10" width="16" height="14" rx="4" fill="white" fillOpacity="0.95" />
        <circle cx="13" cy="16" r="2" fill="#5b21b6" />
        <circle cx="19" cy="16" r="2" fill="#5b21b6" />
        <path
          d="M13 21 Q16 22.5 19 21"
          stroke="#7c3aed"
          strokeWidth="1.2"
          fill="none"
          strokeLinecap="round"
        />
        <rect x="14.5" y="5" width="3" height="4" rx="1" fill="white" fillOpacity="0.9" />
        <circle cx="16" cy="4" r="1.5" fill="#c4b5fd" />
      </svg>
    </div>
  );
}
