"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { earliestDobIso, localTodayIso } from "@/lib/dob";

type Props = {
  value: string;
  onChange: (iso: string) => void;
  invalid?: boolean;
  disabled?: boolean;
  id?: string;
  className?: string;
};

/**
 * DOB field matching the chatbot booking wizard: type into the field or
 * open the native calendar. `max` blocks future dates in the picker;
 * `min` caps age at DOB_MAX_AGE_YEARS.
 */
export function BirthDatePicker({
  value,
  onChange,
  invalid,
  disabled,
  id,
  className,
}: Props) {
  const today = localTodayIso();
  const earliest = earliestDobIso(today);

  return (
    <Input
      id={id}
      type="date"
      autoComplete="bday"
      value={value}
      min={earliest}
      max={today}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid || undefined}
      className={cn(
        "h-9",
        invalid && "border-destructive focus-visible:ring-destructive",
        className
      )}
    />
  );
}
