import type { ClinicType } from "@/types/api";

/** Short suggestion chips for onboarding — never a dump of every possible
 * specialty. Clicking one adds the name; description stays optional. */
export function suggestedSpecialtyNames(
  clinicType: ClinicType | string | undefined
): string[] {
  if (!clinicType) return [];
  return SPECIALTY_TEMPLATES[clinicType as ClinicType] ?? [];
}

export const SPECIALTY_TEMPLATES: Partial<Record<ClinicType, string[]>> = {
  primary_care: [
    "Family Medicine",
    "Internal Medicine",
    "Pediatrics",
    "Women's Health",
    "Geriatrics",
  ],
  medical_specialty: [
    "General Consultation",
    "Chronic Care",
  ],
  neurology: [
    "General Neurology",
    "Headache Medicine",
    "Neuromuscular",
  ],
  cardiology: [
    "General Cardiology",
    "Interventional Cardiology",
    "Electrophysiology",
  ],
  dermatology: [
    "Medical Dermatology",
    "Cosmetic Dermatology",
    "Pediatric Dermatology",
  ],
  aesthetics: [
    "Medical Aesthetics",
    "Cosmetic Dermatology",
    "Laser & Skin",
  ],
  dental: [
    "General Dentistry",
    "Orthodontics",
    "Periodontics",
    "Oral Surgery",
  ],
  physical_therapy: [
    "Orthopedic PT",
    "Sports Rehab",
    "Neurological PT",
  ],
  behavioral_health: [
    "Psychiatry",
    "Psychology",
    "Counseling",
  ],
  laboratory: [
    "Clinical Laboratory",
    "Diagnostic Imaging",
  ],
  urgent_care: ["Urgent Care", "Occupational Medicine"],
  cosmetic_surgery: ["Plastic Surgery", "Reconstructive Surgery"],
  multi_specialty: [
    "Primary Care",
    "Dermatology",
    "Orthopedics",
  ],
};
