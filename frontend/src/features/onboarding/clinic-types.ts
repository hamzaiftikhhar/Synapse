import type { ClinicType } from "@/types/api";

export const CLINIC_TYPE_OPTIONS: Array<{ value: ClinicType; label: string }> = [
  { value: "primary_care", label: "Primary Care" },
  { value: "medical_specialty", label: "Medical Specialty" },
  { value: "neurology", label: "Neurology" },
  { value: "cardiology", label: "Cardiology" },
  { value: "dermatology", label: "Dermatology" },
  { value: "aesthetics", label: "Aesthetics / Med Spa" },
  { value: "dental", label: "Dental" },
  { value: "physical_therapy", label: "Physical Therapy" },
  { value: "behavioral_health", label: "Mental / Behavioral Health" },
  { value: "laboratory", label: "Laboratory / Diagnostics" },
  { value: "urgent_care", label: "Urgent Care" },
  { value: "cosmetic_surgery", label: "Cosmetic / Plastic Surgery" },
  { value: "multi_specialty", label: "Multi-Specialty" },
  { value: "other", label: "Other" },
];
