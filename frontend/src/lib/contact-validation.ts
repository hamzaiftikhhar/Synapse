/** Shared contact/OTP validation — the one place this logic lives so the
 * booking wizard's own contact step and chat identity verification (cancel
 * / reschedule) never drift apart. Frontend validation is UX only; the
 * backend remains the authority on whether a code/contact is actually valid. */

export function isValidEmail(value: string): boolean {
  // Simple production-ready check — not a library, rejects spaces and requires TLD
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/i.test(value.trim());
}

export function isValidPhoneDigits(value: string): boolean {
  // Digits only after stripping common formatting; 7–15 digits (E.164 range)
  const digits = value.replace(/\D/g, "");
  return digits.length >= 7 && digits.length <= 15;
}

export function classifyContact(
  raw: string,
  verificationMode: string
): { phone: string; email: string; error: string | null } {
  const value = raw.trim();
  if (!value) {
    return { phone: "", email: "", error: "Enter an email or phone number for verification" };
  }

  if (verificationMode === "email") {
    if (!isValidEmail(value)) {
      return { phone: "", email: value, error: "Enter a valid email address" };
    }
    return { phone: "", email: value.toLowerCase(), error: null };
  }

  if (verificationMode === "sms") {
    if (!isValidPhoneDigits(value)) {
      return { phone: value, email: "", error: "Enter a valid phone number" };
    }
    return { phone: value, email: "", error: null };
  }

  // sms_or_email | none — accept either, classify by @
  if (value.includes("@")) {
    if (!isValidEmail(value)) {
      return { phone: "", email: value, error: "Enter a valid email address" };
    }
    return { phone: "", email: value.toLowerCase(), error: null };
  }

  if (!isValidPhoneDigits(value)) {
    return {
      phone: value,
      email: "",
      error: "Enter a valid phone number or email address",
    };
  }
  return { phone: value, email: "", error: null };
}

/** Matches settings.OTP_CODE_LENGTH's default (apps/chatbot/services/otp_service.py).
 * Purely a UX box-count/format check — the backend is the real authority. */
export const OTP_LENGTH = 6;

export function isValidOtpCode(value: string): boolean {
  return new RegExp(`^\\d{${OTP_LENGTH}}$`).test(value.trim());
}

export type Country = {
  code: string; // ISO 3166-1 alpha-2
  name: string;
  dialCode: string; // e.g. "+1"
};

// A pragmatic common-countries list, not a full ISO-3166 database — default
// is United States, but nothing assumes every patient is American.
export const COUNTRIES: Country[] = [
  { code: "US", name: "United States", dialCode: "+1" },
  { code: "CA", name: "Canada", dialCode: "+1" },
  { code: "GB", name: "United Kingdom", dialCode: "+44" },
  { code: "AU", name: "Australia", dialCode: "+61" },
  { code: "MX", name: "Mexico", dialCode: "+52" },
  { code: "IN", name: "India", dialCode: "+91" },
  { code: "PH", name: "Philippines", dialCode: "+63" },
  { code: "DE", name: "Germany", dialCode: "+49" },
  { code: "FR", name: "France", dialCode: "+33" },
  { code: "ES", name: "Spain", dialCode: "+34" },
  { code: "BR", name: "Brazil", dialCode: "+55" },
  { code: "NG", name: "Nigeria", dialCode: "+234" },
  { code: "PK", name: "Pakistan", dialCode: "+92" },
  { code: "AE", name: "United Arab Emirates", dialCode: "+971" },
];

export const DEFAULT_COUNTRY = COUNTRIES[0];
