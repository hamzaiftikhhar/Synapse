"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { COUNTRIES, DEFAULT_COUNTRY } from "@/lib/contact-validation";

/** Country selector + national number, composed into a single E.164-ish
 * string (e.g. "+15551234567") reported via onChange. Defaults to the US
 * but never assumes the patient is American — reusable anywhere a phone
 * number needs to be collected. */
export function PhoneInput({
  onChange,
  className,
  autoFocus,
  disabled,
}: {
  onChange: (value: string) => void;
  className?: string;
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const [countryCode, setCountryCode] = useState(DEFAULT_COUNTRY.code);
  const [national, setNational] = useState("");

  const country = COUNTRIES.find((c) => c.code === countryCode) ?? DEFAULT_COUNTRY;

  function emit(dialCode: string, nextNational: string) {
    const digits = nextNational.replace(/\D/g, "");
    onChange(digits ? `${dialCode}${digits}` : "");
  }

  return (
    <div className={cn("flex gap-1.5", className)}>
      <Select
        value={countryCode}
        onValueChange={(v) => {
          if (!v) return;
          setCountryCode(v);
          const next = COUNTRIES.find((c) => c.code === v) ?? country;
          emit(next.dialCode, national);
        }}
      >
        <SelectTrigger
          className="h-9 w-auto min-w-[4.75rem] shrink-0 gap-1 px-2"
          aria-label="Country code"
          disabled={disabled}
        >
          <SelectValue>{country.dialCode}</SelectValue>
        </SelectTrigger>
        <SelectContent
          className="z-[80] w-max min-w-[16rem] max-w-[min(22rem,calc(100vw-2rem))]"
          alignItemWithTrigger={false}
          align="start"
        >
          {COUNTRIES.map((c) => (
            <SelectItem key={c.code} value={c.code}>
              {c.name} ({c.dialCode})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        autoFocus={autoFocus}
        disabled={disabled}
        value={national}
        onChange={(e) => {
          setNational(e.target.value);
          emit(country.dialCode, e.target.value);
        }}
        placeholder="Phone number"
        className="h-9 flex-1 rounded-lg text-sm"
      />
    </div>
  );
}
