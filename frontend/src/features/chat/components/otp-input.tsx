"use client";

import { useRef } from "react";
import { cn } from "@/lib/utils";
import { OTP_LENGTH } from "@/lib/contact-validation";

/** Segmented numeric code input — length matches settings.OTP_CODE_LENGTH's
 * default. Supports typing, backspace-to-previous, arrow navigation, and
 * pasting the full code at once. Purely presentational: parent owns the
 * value and decides when to submit. */
export function OtpInput({
  value,
  onChange,
  length = OTP_LENGTH,
  disabled,
  error,
  autoFocus,
}: {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  disabled?: boolean;
  error?: boolean;
  autoFocus?: boolean;
}) {
  const inputRefs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = value.split("").slice(0, length);

  function setDigit(index: number, digit: string) {
    const next = value.split("");
    next[index] = digit;
    onChange(next.join("").slice(0, length));
  }

  function handleChange(index: number, raw: string) {
    const digit = raw.replace(/\D/g, "").slice(-1);
    if (!digit) {
      setDigit(index, "");
      return;
    }
    setDigit(index, digit);
    if (index < length - 1) inputRefs.current[index + 1]?.focus();
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === "ArrowLeft" && index > 0) {
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === "ArrowRight" && index < length - 1) {
      inputRefs.current[index + 1]?.focus();
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
    if (!pasted) return;
    e.preventDefault();
    onChange(pasted);
    const focusIndex = Math.min(pasted.length, length - 1);
    inputRefs.current[focusIndex]?.focus();
  }

  return (
    <div className="flex gap-1.5" role="group" aria-label="Verification code">
      {Array.from({ length }).map((_, i) => (
        <input
          key={i}
          ref={(el) => {
            inputRefs.current[i] = el;
          }}
          type="text"
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={1}
          autoFocus={autoFocus && i === 0}
          disabled={disabled}
          value={digits[i] ?? ""}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
          aria-label={`Digit ${i + 1} of ${length}`}
          className={cn(
            "h-10 w-8 rounded-lg border border-input bg-transparent text-center text-base font-medium outline-none transition-colors",
            "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            "disabled:pointer-events-none disabled:opacity-50",
            error && "border-destructive ring-3 ring-destructive/20"
          )}
        />
      ))}
    </div>
  );
}
