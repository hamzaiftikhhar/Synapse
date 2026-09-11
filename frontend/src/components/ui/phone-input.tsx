"use client";

import { useMemo, useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { COUNTRIES, DEFAULT_COUNTRY, type Country } from "@/lib/contact-validation";

/** Country-code selector + national-number field, emitting a single E.164
 * string via onChange. Replaces bare `<Input type="tel">` fields that
 * relied on normalizePhone()'s "assume +1 for 10 bare digits" guess —
 * with an explicit country selected here, there's nothing left to guess. */
export function PhoneInput({
  value,
  onChange,
  disabled,
  placeholder = "415 555 0123",
  "aria-invalid": ariaInvalid,
  id,
}: {
  value: string;
  onChange: (e164: string) => void;
  disabled?: boolean;
  placeholder?: string;
  "aria-invalid"?: boolean;
  id?: string;
}) {
  const initialCountry = useMemo(() => {
    const match = COUNTRIES.find((c) => value.startsWith(c.dialCode));
    return match || DEFAULT_COUNTRY;
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps -- only ever re-derive from the *initial* value
  const [country, setCountry] = useState<Country>(initialCountry);

  const national = value.startsWith(country.dialCode)
    ? value.slice(country.dialCode.length).trim()
    : value.replace(/^\+\d*/, "").trim();

  function emit(nextCountry: Country, nextNational: string) {
    const digits = nextNational.replace(/\D/g, "");
    onChange(digits ? `${nextCountry.dialCode}${digits}` : "");
  }

  return (
    <div className="flex gap-1.5">
      <Select
        value={country.code}
        onValueChange={(code) => {
          const next = COUNTRIES.find((c) => c.code === code) || DEFAULT_COUNTRY;
          setCountry(next);
          emit(next, national);
        }}
        items={COUNTRIES.map((c) => ({ value: c.code, label: `${c.name} (${c.dialCode})` }))}
        disabled={disabled}
      >
        <SelectTrigger className="w-[5.5rem] shrink-0" aria-label="Country code">
          <SelectValue>{country.dialCode}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {COUNTRIES.map((c) => (
            <SelectItem key={c.code} value={c.code}>
              {c.name} ({c.dialCode})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        id={id}
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        value={national}
        onChange={(e) => emit(country, e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={ariaInvalid}
        className="flex-1"
      />
    </div>
  );
}
