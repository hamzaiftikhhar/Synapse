import type { ClinicType } from "@/types/api";

export const CLINIC_TYPE_OPTIONS: Array<{ value: ClinicType; label: string }> = [
  { value: "dermatology", label: "Dermatology" },
  { value: "dental", label: "Dental" },
  { value: "aesthetics", label: "Aesthetics / Med Spa" },
  { value: "general_medicine", label: "General Medicine" },
  { value: "urgent_care", label: "Urgent Care" },
  { value: "laboratory", label: "Laboratory" },
  { value: "cosmetic_surgery", label: "Cosmetic / Plastic Surgery" },
  { value: "multi_specialty", label: "Multi-Specialty" },
  { value: "other", label: "Other" },
];
