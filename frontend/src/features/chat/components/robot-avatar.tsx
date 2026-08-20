"use client";

import { cn } from "@/lib/utils";
import {
  avatarMediaStyle,
  useWidgetTheme,
  type WidgetThemeValue,
} from "@/features/chat/widget-theme";

function FaceMark({
  className,
  themed,
}: {
  className?: string;
  themed: boolean;
}) {
  const fill = themed ? "currentColor" : "#E8EEF9";
  const stroke = themed ? "currentColor" : "#A8B8D8";
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <circle cx="11.5" cy="14" r="2.1" fill={fill} fillOpacity={themed ? 0.95 : 1} />
      <circle cx="20.5" cy="14" r="2.1" fill={fill} fillOpacity={themed ? 0.95 : 1} />
      <path
        d="M12 20.5c1.4 1.4 6.6 1.4 8 0"
        stroke={stroke}
        strokeOpacity={themed ? 0.75 : 1}
        strokeWidth="1.7"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

function AvatarMedia({ theme, src }: { theme: WidgetThemeValue | null; src?: string }) {
  const image = src || theme?.avatarUrl || "";
  if (!image) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={image}
      alt=""
      className="pointer-events-none"
      style={avatarMediaStyle(
        theme?.avatarZoom ?? 1,
        theme?.avatarOffsetX ?? 0,
        theme?.avatarOffsetY ?? 0
      )}
    />
  );
}

/** Professional clinic-assistant mark — navy geometric face, not cartoon robot. */
export function RobotAvatar({
  size = "md",
  className,
  animate = false,
  src,
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
  animate?: boolean;
  src?: string;
}) {
  const dim = size === "sm" ? "size-7" : size === "lg" ? "size-11" : "size-9";
  const theme = useWidgetTheme();
  const themed = theme != null;
  const image = src || theme?.avatarUrl;

  return (
    <div
      className={cn(
        "relative flex shrink-0 items-center justify-center overflow-hidden rounded-[10px] shadow-sm",
        dim,
        !themed && "bg-primary text-primary-foreground",
        className
      )}
      style={
        themed
          ? { backgroundColor: theme.primaryColor, color: theme.resolvedText }
          : undefined
      }
      aria-hidden
    >
      {image ? (
        <AvatarMedia theme={theme} src={src} />
      ) : (
        <FaceMark
          themed={themed}
          className={cn(
            "size-[62%]",
            animate && "animate-[robot-blink_4s_ease-in-out_infinite]"
          )}
        />
      )}
    </div>
  );
}

export function RobotLauncherIcon({ className }: { className?: string }) {
  const theme = useWidgetTheme();
  const themed = theme != null;
  const image = theme?.avatarUrl;

  return (
    <div
      className={cn(
        "relative flex size-full items-center justify-center overflow-hidden rounded-[10px]",
        !themed && "bg-primary text-primary-foreground",
        className
      )}
      style={
        themed
          ? { backgroundColor: theme.primaryColor, color: theme.resolvedText }
          : undefined
      }
    >
      {image ? (
        <AvatarMedia theme={theme} />
      ) : (
        <FaceMark themed={themed} className="size-6" />
      )}
    </div>
  );
}
