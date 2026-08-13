import type { ImportRecordType } from "@/types/api";

export type TemplateColumn = {
  key: string;
  header: string;
  required: boolean;
  hint: string;
};

export type ImportTemplate = {
  fileStem: string;
  summary: string;
  notes?: string[];
  columns: TemplateColumn[];
  sampleRows: string[][];
};

export const IMPORT_TEMPLATES: Record<ImportRecordType, ImportTemplate> = {
  providers: {
    fileStem: "synapse-providers",
    summary: "One row per clinician. Name is required — credentials, bio, and languages can be blank.",
    notes: [
      "Leave languages blank if you don't know them — we will not assume English.",
    ],
    columns: [
      {
        key: "full_name",
        header: "Provider Name",
        required: true,
        hint: "How they appear in booking, e.g. Dr. Chloe Bennett",
      },
      {
        key: "title",
        header: "Credentials",
        required: false,
        hint: "Optional. Short credentials or role, e.g. MD, FAAD or PA-C",
      },
      {
        key: "bio",
        header: "Bio",
        required: false,
        hint: "Optional. A short public description patients might see",
      },
      {
        key: "languages",
        header: "Languages",
        required: false,
        hint: "Optional. Comma-separated, e.g. English, Spanish. Leave blank if unknown.",
      },
    ],
    sampleRows: [
      [
        "Dr. Chloe Bennett",
        "MD, FAAD",
        "Board-certified dermatologist.",
        "English, Spanish",
      ],
      ["Julian Reyes", "PA-C", "", ""],
      ["Dr. Maya Lin", "", "Surgical and cosmetic procedures.", "English, Mandarin"],
    ],
  },
  services: {
    fileStem: "synapse-services",
    summary:
      "One row per bookable service. Name is required. Description, category, duration, and price can be blank.",
    notes: [
      "If duration is blank, we'll use 30 minutes by default.",
      "Price can be 150 or $150.00. Leave it blank for call-for-pricing.",
    ],
    columns: [
      {
        key: "name",
        header: "Service Name",
        required: true,
        hint: "What patients book, e.g. Acne Consultation",
      },
      {
        key: "description",
        header: "Description",
        required: false,
        hint: "Optional note shown in the catalog",
      },
      {
        key: "category",
        header: "Category",
        required: false,
        hint: "Optional grouping, e.g. Medical or Cosmetic",
      },
      {
        key: "duration_min",
        header: "Duration (min)",
        required: false,
        hint: "Optional. Leave blank to use 30 minutes.",
      },
      {
        key: "price_cents",
        header: "Price",
        required: false,
        hint: "Optional. Dollars, e.g. 150 or $150.00 — not cents",
      },
    ],
    sampleRows: [
      ["Acne Consultation", "New patient acne visit", "Medical", "30", "150"],
      ["Botox", "", "Cosmetic", "", "299"],
      ["Follow-up Visit", "Established patient follow-up", "", "15", ""],
    ],
  },
  specialties: {
    fileStem: "synapse-specialties",
    summary: "One row per area of care. Name is required. Description can be blank.",
    columns: [
      {
        key: "name",
        header: "Specialty Name",
        required: true,
        hint: "Broad area of care, e.g. Dermatology",
      },
      {
        key: "description",
        header: "Description",
        required: false,
        hint: "Optional note for your team",
      },
    ],
    sampleRows: [
      ["Dermatology", "Medical and surgical skin care"],
      ["Cosmetic Dermatology", ""],
      ["Pediatric Dermatology", "Skin care for children"],
    ],
  },
  insurance: {
    fileStem: "synapse-insurance",
    summary: "One row per accepted payer. Insurance name is required — plan and network can be blank.",
    notes: ["Plan name and network/type are optional. A payer-only row is valid."],
    columns: [
      {
        key: "provider_name",
        header: "Insurance Name",
        required: true,
        hint: "Payer or carrier patients know, e.g. Aetna",
      },
      {
        key: "plan_name",
        header: "Plan name",
        required: false,
        hint: "Optional product name, e.g. Gold",
      },
      {
        key: "plan_type",
        header: "Network / type",
        required: false,
        hint: "Optional network, e.g. PPO or HMO",
      },
    ],
    sampleRows: [
      ["Aetna", "", "PPO"],
      ["Blue Cross Blue Shield", "Gold", "HMO"],
      ["Cigna", "", ""],
    ],
  },
};

function escapeCsv(value: string) {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

function toCsv(headers: string[], rows: string[][]) {
  return [headers, ...rows].map((row) => row.map(escapeCsv).join(",")).join("\n");
}

export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([`\uFEFF${csv}\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadSampleCsv(recordType: ImportRecordType) {
  const template = IMPORT_TEMPLATES[recordType];
  const headers = template.columns.map((c) => c.header);
  downloadCsv(`${template.fileStem}-sample.csv`, toCsv(headers, template.sampleRows));
}

export function downloadEmptyCsv(recordType: ImportRecordType) {
  const template = IMPORT_TEMPLATES[recordType];
  const headers = template.columns.map((c) => c.header);
  const emptyRows = template.sampleRows.map((row) => row.map(() => ""));
  downloadCsv(`${template.fileStem}-template.csv`, toCsv(headers, emptyRows));
}
