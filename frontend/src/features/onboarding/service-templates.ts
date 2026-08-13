import type { ClinicType } from "@/types/api";

/** Map free-text specialty names onto clinic-type template sets. Used only
 * to rank onboarding suggestions — never written to the database and never
 * creates a Specialty → Service relationship. */
const SPECIALTY_TEMPLATE_HINTS: Array<{ pattern: RegExp; types: ClinicType[] }> = [
  { pattern: /dermat|skin|acne|mole|psoriasis/i, types: ["dermatology", "aesthetics"] },
  { pattern: /aesthetic|cosmetic|botox|filler|med\s*spa|laser|peel/i, types: ["aesthetics"] },
  { pattern: /dental|orthodont|teeth|oral|invisalign/i, types: ["dental"] },
  { pattern: /cardio|heart/i, types: ["cardiology"] },
  { pattern: /neuro|migraine|seizure/i, types: ["neurology"] },
  { pattern: /physical\s*therap|rehab|sports\s*injur/i, types: ["physical_therapy"] },
  { pattern: /behavio|mental\s*health|psychiatr|psycholog/i, types: ["behavioral_health"] },
  { pattern: /lab|diagnostic|patholog|blood/i, types: ["laboratory"] },
  { pattern: /primary\s*care|family\s*med|internal\s*med|gp\b/i, types: ["primary_care"] },
];

function addTemplates(into: ServiceTemplate[], seen: Set<string>, list: ServiceTemplate[] | undefined) {
  if (!list) return;
  for (const template of list) {
    const key = template.name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    into.push(template);
  }
}

/** Clinic-type templates first, then extra sets hinted by specialty names
 * the owner already entered. Deduped by service name. */
export function suggestedServiceTemplates(
  clinicType: ClinicType | string | undefined,
  specialtyNames: string[]
): ServiceTemplate[] {
  const seen = new Set<string>();
  const out: ServiceTemplate[] = [];

  if (clinicType) addTemplates(out, seen, SERVICE_TEMPLATES[clinicType as ClinicType]);

  const hinted = new Set<ClinicType>();
  for (const name of specialtyNames) {
    for (const hint of SPECIALTY_TEMPLATE_HINTS) {
      if (hint.pattern.test(name)) {
        for (const type of hint.types) hinted.add(type);
      }
    }
  }
  for (const type of hinted) {
    if (type === clinicType) continue;
    addTemplates(out, seen, SERVICE_TEMPLATES[type]);
  }

  return out;
}

export type ServiceTemplate = {
  name: string;
  duration_min: number;
  price_cents: number | null;
  category?: string;
};

/** Suggestions only — never written to the database directly. Clicking one
 * in the onboarding Services step pre-fills the existing "Add service"
 * form; the owner can still rename, reprice, or skip it entirely. Not
 * every clinic type has a natural template set (e.g. Urgent Care, Cosmetic
 * Surgery, Multi-Specialty, Other are intentionally omitted). */
export const SERVICE_TEMPLATES: Partial<Record<ClinicType, ServiceTemplate[]>> = {
  primary_care: [
    { name: "Annual Physical", duration_min: 30, price_cents: null },
    { name: "New Patient Visit", duration_min: 45, price_cents: null },
    { name: "Follow-up Visit", duration_min: 15, price_cents: null },
    { name: "Preventive Care Visit", duration_min: 30, price_cents: null },
    { name: "Chronic Disease Management", duration_min: 30, price_cents: null },
  ],
  medical_specialty: [
    { name: "New Patient Consultation", duration_min: 45, price_cents: null },
    { name: "Follow-up Visit", duration_min: 20, price_cents: null },
    { name: "Diagnostic Review", duration_min: 30, price_cents: null },
  ],
  neurology: [
    { name: "Neurology Consultation", duration_min: 45, price_cents: null },
    { name: "Migraine Evaluation", duration_min: 30, price_cents: null },
    { name: "EEG", duration_min: 60, price_cents: null },
    { name: "Follow-up Visit", duration_min: 20, price_cents: null },
    { name: "Memory Evaluation", duration_min: 45, price_cents: null },
  ],
  cardiology: [
    { name: "Cardiology Consultation", duration_min: 45, price_cents: null },
    { name: "EKG", duration_min: 20, price_cents: null },
    { name: "Echocardiogram", duration_min: 45, price_cents: null },
    { name: "Stress Test", duration_min: 60, price_cents: null },
    { name: "Follow-up Visit", duration_min: 20, price_cents: null },
  ],
  dermatology: [
    { name: "Skin Consultation", duration_min: 30, price_cents: null },
    { name: "Full Body Skin Exam", duration_min: 30, price_cents: null },
    { name: "Mole Check", duration_min: 15, price_cents: null },
    { name: "Acne Consultation", duration_min: 30, price_cents: null },
  ],
  aesthetics: [
    { name: "Botox", duration_min: 30, price_cents: null },
    { name: "Dermal Fillers", duration_min: 45, price_cents: null },
    { name: "Chemical Peel", duration_min: 30, price_cents: null },
    { name: "Laser Treatment", duration_min: 45, price_cents: null },
    { name: "Skin Consultation", duration_min: 30, price_cents: null },
  ],
  dental: [
    { name: "Dental Cleaning", duration_min: 45, price_cents: null },
    { name: "Exam", duration_min: 30, price_cents: null },
    { name: "Root Canal", duration_min: 90, price_cents: null },
    { name: "Whitening", duration_min: 60, price_cents: null },
    { name: "Extraction", duration_min: 30, price_cents: null },
  ],
  physical_therapy: [
    { name: "Initial Evaluation", duration_min: 60, price_cents: null },
    { name: "Follow-up Session", duration_min: 45, price_cents: null },
    { name: "Post-Surgical Rehab", duration_min: 45, price_cents: null },
    { name: "Sports Injury Assessment", duration_min: 45, price_cents: null },
  ],
  behavioral_health: [
    { name: "Initial Consultation", duration_min: 60, price_cents: null },
    { name: "Individual Therapy Session", duration_min: 50, price_cents: null },
    { name: "Medication Management", duration_min: 30, price_cents: null },
    { name: "Follow-up Session", duration_min: 30, price_cents: null },
  ],
  laboratory: [
    { name: "Blood Panel", duration_min: 15, price_cents: null },
    { name: "Urinalysis", duration_min: 10, price_cents: null },
    { name: "Specimen Collection", duration_min: 15, price_cents: null },
    { name: "Diagnostic Screening", duration_min: 20, price_cents: null },
  ],
};
