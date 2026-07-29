"use client";

import type { ChatMessage } from "@/types/chat";

export function ImageMessage({ message }: { message: ChatMessage }) {
  const src = (message.payload?.src as string) || "";
  const alt = (message.payload?.alt as string) || "Image";
  if (!src) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      className="max-h-56 w-full rounded-[6px] border border-border object-cover"
    />
  );
}
