"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  generating,
  disabled,
  placeholder = "Write a message",
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  generating?: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const typing = value.trim().length > 0;

  useLayoutEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }, [value]);

  useEffect(() => {
    if (!generating) taRef.current?.focus();
  }, [generating]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!generating && value.trim()) onSubmit();
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (generating) {
      onStop?.();
      return;
    }
    onSubmit();
  }

  const canSend = Boolean(value.trim()) && !disabled;

  return (
    <form
      onSubmit={handleSubmit}
      className="shrink-0 bg-[#f7f6fb] px-3 pb-2 pt-2 sm:px-4"
    >
      <div
        className={cn(
          "synapse-chat-composer px-3.5 pb-2.5 pt-3",
          typing && !generating && "synapse-chat-composer--typing"
        )}
      >
        <textarea
          ref={taRef}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled && !generating}
          autoComplete="off"
          className="max-h-[140px] min-h-[28px] w-full resize-none bg-transparent text-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground/70 disabled:opacity-60"
        />

        <div className="mt-1.5 flex items-center justify-end">
          <button
            type="submit"
            disabled={generating ? false : !canSend}
            aria-label={generating ? "Stop generating" : "Send message"}
            className={cn(
              "synapse-chat-send flex size-9 items-center justify-center rounded-full shadow-sm",
              generating
                ? "bg-primary text-primary-foreground"
                : canSend
                  ? "bg-primary text-primary-foreground"
                  : "bg-neutral-200 text-neutral-400"
            )}
          >
            <span className="relative flex size-4 items-center justify-center">
              <ArrowUp
                className={cn(
                  "synapse-chat-send-icon absolute size-4",
                  generating
                    ? "scale-75 opacity-0"
                    : "scale-100 opacity-100"
                )}
                strokeWidth={2.5}
              />
              <Square
                className={cn(
                  "synapse-chat-send-icon absolute size-3 fill-current",
                  generating
                    ? "scale-100 opacity-100"
                    : "scale-75 opacity-0"
                )}
                strokeWidth={0}
              />
            </span>
          </button>
        </div>
      </div>
      <p className="mt-2 text-center text-[10px] text-muted-foreground/80">
        AI can make mistakes. Review for accuracy.
      </p>
    </form>
  );
}
