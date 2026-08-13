import type { ImportRecordType } from "@/types/api";

export const SPREADSHEET_ACCEPT =
  ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export function isSpreadsheetFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return name.endsWith(".csv") || name.endsWith(".xlsx");
}

export const RECORD_TYPE_LABEL: Record<ImportRecordType, string> = {
  providers: "Providers",
  services: "Services",
  specialties: "Specialties",
};

// Mirrors apps/importer/target_schemas.py — the fixed catalog the backend
// mapper/extractor accept. Keep in sync if the backend catalog changes.
export const TARGET_FIELD_LABELS: Record<ImportRecordType, Record<string, string>> = {
  providers: {
    full_name: "Name",
    title: "Title / credentials",
    bio: "Bio",
    languages: "Languages",
  },
  services: {
    name: "Name",
    description: "Description",
    category: "Category",
    duration_min: "Duration (min)",
    price_cents: "Price",
  },
  specialties: {
    name: "Name",
    description: "Description",
  },
};

export function targetFieldOptions(recordType: ImportRecordType) {
  return Object.entries(TARGET_FIELD_LABELS[recordType]).map(([value, label]) => ({
    value,
    label,
  }));
}

export function formatFieldValue(value: unknown, field?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field === "price_cents" && typeof value === "number") return `$${(value / 100).toFixed(2)}`;
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}
