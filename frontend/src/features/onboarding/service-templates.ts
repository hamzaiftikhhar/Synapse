import type { ClinicType } from "@/types/api";

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
