/** Geometric clinician + watermark marks — limited purple palette, dark outlines. */
export function ClinicianIllustration({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 260 300" className={className} aria-hidden fill="none">
      <circle cx="198" cy="64" r="48" fill="#cfc3ff" opacity="0.4" />
      <circle cx="42" cy="228" r="34" fill="#9b7dff" opacity="0.2" />
      <g fill="none" stroke="#6b3cf0" strokeWidth="1.5" opacity="0.32">
        <rect x="18" y="38" width="26" height="20" rx="3" />
        <path d="M25 48h12M31 42v12" />
        <rect x="206" y="128" width="18" height="12" rx="6" />
        <circle cx="215" cy="134" r="2.2" />
        <path d="M34 168c7 0 11 7 18 7s11-7 18-7" />
        <path d="M214 178c5-8 16-8 21 0M224.5 169v4M224.5 187v4M216 178h4M229 178h4" />
      </g>
      {/* hair */}
      <path
        d="M118 92c2-38 28-58 52-58 26 0 50 22 50 56 0 10-3 18-8 24-18-6-28-4-42-4s-28-1-44 4c-5-8-8-14-8-22z"
        fill="#1c1338"
      />
      {/* neck */}
      <rect x="154" y="118" width="22" height="18" rx="6" fill="#f3e6d8" />
      {/* face */}
      <ellipse cx="165" cy="96" rx="26" ry="28" fill="#f3e6d8" />
      {/* mask */}
      <path
        d="M144 100c8 14 34 14 42 0v5c-8 16-34 16-42 0v-5z"
        fill="#f7f4ff"
        stroke="#1c1338"
        strokeWidth="1.35"
      />
      <path d="M144 102c-9-1-15 6-13 13" stroke="#1c1338" strokeWidth="1.35" />
      <path d="M186 102c9-1 15 6 13 13" stroke="#1c1338" strokeWidth="1.35" />
      {/* coat */}
      <path
        d="M108 148c10-20 28-32 57-32 29 0 47 12 57 32l10 98H98l10-98z"
        fill="#fff"
        stroke="#1c1338"
        strokeWidth="1.7"
      />
      {/* lapel */}
      <path d="M165 148v36" stroke="#1c1338" strokeWidth="1.4" />
      <path d="M148 150l17 22M182 150l-17 22" stroke="#1c1338" strokeWidth="1.2" />
      {/* scrubs */}
      <path d="M136 176h58v62c0 8-7 14-16 14h-26c-9 0-16-6-16-14v-62z" fill="#6b3cf0" />
      {/* left arm + clipboard */}
      <path
        d="M112 168c-16 14-18 36-8 52"
        stroke="#1c1338"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
      <rect x="78" y="196" width="44" height="54" rx="4" fill="#2a1848" stroke="#1c1338" strokeWidth="1.5" />
      <rect x="84" y="192" width="16" height="8" rx="2" fill="#9b7dff" />
      <path d="M86 210h28M86 220h22M86 230h26" stroke="#cfc3ff" strokeWidth="1.5" />
      {/* plus badge */}
      <circle cx="206" cy="212" r="11" fill="#e45a9a" />
      <path d="M206 206v12M200 212h12" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export type GlyphName =
  | "pulse"
  | "calendar"
  | "people"
  | "chat"
  | "folder"
  | "stethoscope"
  | "tokens"
  | "booking";

export function MetricGlyph({
  name,
  className,
}: {
  name: GlyphName;
  className?: string;
}) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden fill="none">
      {name === "pulse" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#ece6ff" />
          <path
            d="M8 26h8l3-8 5 16 4-10h12"
            stroke="#6b3cf0"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="36" cy="16" r="5" fill="#e45a9a" />
        </>
      ) : null}
      {name === "calendar" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#e8eeff" />
          <rect x="10" y="12" width="28" height="26" rx="4" stroke="#4a52d4" strokeWidth="2" />
          <path d="M10 20h28" stroke="#4a52d4" strokeWidth="2" />
          <path d="M18 10v6M30 10v6" stroke="#4a52d4" strokeWidth="2" strokeLinecap="round" />
          <circle cx="19" cy="28" r="2" fill="#6b3cf0" />
          <circle cx="29" cy="28" r="2" fill="#e45a9a" />
        </>
      ) : null}
      {name === "people" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#efe8ff" />
          <circle cx="20" cy="18" r="6" fill="#6b3cf0" />
          <path d="M8 36c1-8 6-12 12-12s11 4 12 12" fill="#9b7dff" />
          <circle cx="32" cy="18" r="5" fill="#2a1848" />
          <path d="M28 36c1-6 4-9 8-9 5 0 9 4 10 9" fill="#cfc3ff" />
        </>
      ) : null}
      {name === "chat" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#f3e8ff" />
          <path d="M12 14h24v16H20l-8 6v-6H12V14z" fill="#6b3cf0" />
          <path d="M18 20h12M18 25h8" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
        </>
      ) : null}
      {name === "folder" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#ece6ff" />
          <path d="M10 18h10l3 4h15v16H10V18z" fill="#9b7dff" />
          <path d="M10 22h28v16H10z" fill="#6b3cf0" />
        </>
      ) : null}
      {name === "stethoscope" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#e8eeff" />
          <path
            d="M16 12v10c0 8 6 14 14 14"
            stroke="#2a1848"
            strokeWidth="2.2"
            strokeLinecap="round"
          />
          <path d="M32 12v10" stroke="#6b3cf0" strokeWidth="2.2" strokeLinecap="round" />
          <circle cx="30" cy="36" r="6" stroke="#e45a9a" strokeWidth="2.2" />
          <circle cx="16" cy="12" r="3" fill="#6b3cf0" />
          <circle cx="32" cy="12" r="3" fill="#6b3cf0" />
        </>
      ) : null}
      {name === "tokens" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#ece6ff" />
          <rect x="12" y="22" width="6" height="14" rx="2" fill="#cfc3ff" />
          <rect x="21" y="14" width="6" height="22" rx="2" fill="#9b7dff" />
          <rect x="30" y="18" width="6" height="18" rx="2" fill="#6b3cf0" />
        </>
      ) : null}
      {name === "booking" ? (
        <>
          <rect width="48" height="48" rx="8" fill="#f3e8ff" />
          <circle cx="24" cy="24" r="12" stroke="#6b3cf0" strokeWidth="2.2" />
          <path d="M24 16v8l5 3" stroke="#e45a9a" strokeWidth="2.2" strokeLinecap="round" />
        </>
      ) : null}
    </svg>
  );
}