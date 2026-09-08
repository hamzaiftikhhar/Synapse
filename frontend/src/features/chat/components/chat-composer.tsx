"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { ArrowUp, MoreHorizontal, Square } from "lucide-react";
import { ICONS } from "@/features/chat/components/action-buttons";
import { cn } from "@/lib/utils";

export type ComposerQuickAction = {
  id: string;
  label: string;
  message: string;
  icon?: string;
};

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  generating,
  disabled,
  placeholder = "Write a message",
  quickActions,
  onQuickAction,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  generating?: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** The system's own tool calls (find a doctor, book, check insurance,
   * hours) — always reachable from the "..." button, not only as
   * contextual chips after a reply or the empty-state starters. */
  quickActions?: ComposerQuickAction[];
  onQuickAction?: (action: ComposerQuickAction) => void;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const typing = value.trim().length > 0;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDoc(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

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
      className="shrink-0 bg-background px-3 pb-2 pt-2 sm:px-4"
    >
      <div
        role="group"
        className={cn(
          "synapse-chat-composer flex cursor-text items-end gap-1.5 py-2.5 pl-2 pr-2",
          typing && !generating && "synapse-chat-composer--typing"
        )}
        onMouseDown={(e) => {
          // Whole shell focuses the field — not only the textarea hit box.
          const target = e.target as HTMLElement;
          if (target.closest("button, a, input, textarea, [role='button']")) {
            return;
          }
          e.preventDefault();
          taRef.current?.focus();
        }}
      >
        {quickActions?.length ? (
          <div className="relative shrink-0" ref={menuRef}>
            <button
              type="button"
              title="More"
              aria-label="Quick actions"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
              className="flex size-8 items-center justify-center rounded-full text-muted-foreground transition-[background-color,color] duration-150 hover:bg-accent hover:text-foreground"
            >
              <MoreHorizontal className="size-4" />
            </button>
            {menuOpen ? (
              <div
                role="menu"
                className="absolute bottom-full left-0 z-20 mb-2 min-w-[190px] origin-bottom-left rounded-xl border border-border bg-popover p-1 shadow-lg"
                style={{ animation: "synapse-panel-in 200ms ease-out both" }}
              >
                {quickActions.map((action) => {
                  const Icon = ICONS[action.icon ?? ""] ?? undefined;
                  return (
                    <button
                      key={action.id}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false);
                        onQuickAction?.(action);
                      }}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-foreground transition-[background-color] duration-150 hover:bg-accent"
                    >
                      {Icon ? (
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                      ) : null}
                      {action.label}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
        ) : null}

        <textarea
          ref={taRef}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled && !generating}
          autoComplete="off"
          // flex-1 + the button as a sibling (not an absolute overlay) is
          // what actually reserves the button's width for free — text
          // wraps once it would run into the button's column, no manual
          // padding-reservation hack needed. `block` on a <textarea>
          // (default is inline-block) avoids the classic phantom-descender-
          // space gap that inline-block form elements leave below
          // themselves in normal flow — that gap, not the padding, was why
          // the bottom of the box previously looked taller than the top.
          className="block max-h-[140px] min-h-[24px] flex-1 resize-none bg-transparent py-0.5 text-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground/70 disabled:opacity-60"
        />

        <button
          type="submit"
          disabled={generating ? false : !canSend}
          aria-label={generating ? "Stop generating" : "Send message"}
          className={cn(
            "synapse-chat-send flex size-8 shrink-0 items-center justify-center rounded-full shadow-sm",
            generating
              ? "bg-primary text-primary-foreground"
              : canSend
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground"
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
      <p className="mt-2 text-center text-[10px] text-muted-foreground/80">
        AI can make mistakes. Review for accuracy.
      </p>
    </form>
  );
}
