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
  columns: TemplateColumn[];
  sampleRows: string[][];
};

export const IMPORT_TEMPLATES: Record<ImportRecordType, ImportTemplate> = {
  providers: {
    fileStem: "synapse-providers",
    summary: "One row per clinician. Name is required — title, bio, and languages can wait.",
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
        hint: "Short credentials or role, e.g. MD, FAAD or PA-C",
      },
      {
        key: "bio",
        header: "Bio",
        required: false,
        hint: "A short public description patients might see",
      },
      {
        key: "languages",
        header: "Languages",
        required: false,
        hint: "Comma-separated, e.g. English, Spanish",
      },
    ],
    sampleRows: [
      [
        "Dr. Chloe Bennett",
        "MD, FAAD",
        "Board-certified dermatologist.",
        "English, Spanish",
      ],
      ["Julian Reyes", "PA-C", "Focuses on medical dermatology.", "English, Tagalog"],
      ["Dr. Maya Lin", "MD", "Surgical and cosmetic procedures.", "English, Mandarin"],
    ],
  },
  services: {
    fileStem: "synapse-services",
    summary: "One row per bookable service. Name is required. Price can be 150 or $150.00.",
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
        hint: "Appointment length in minutes, e.g. 30",
      },
      {
        key: "price_cents",
        header: "Price",
        required: false,
        hint: "Dollars, e.g. 150 or $150.00 — not cents",
      },
    ],
    sampleRows: [
      ["Acne Consultation", "New patient acne visit", "Medical", "30", "150"],
      ["Botox", "Cosmetic neuromodulator treatment", "Cosmetic", "20", "299"],
      ["Follow-up Visit", "Established patient follow-up", "Medical", "15", "85"],
    ],
  },
  specialties: {
    fileStem: "synapse-specialties",
    summary: "One row per area of care. Name is required.",
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
      ["Cosmetic Dermatology", "Aesthetic procedures"],
      ["Pediatric Dermatology", "Skin care for children"],
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
