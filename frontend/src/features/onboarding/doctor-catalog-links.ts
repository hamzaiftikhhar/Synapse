import type { Doctor, DoctorUpdateInput, Service, Specialty } from "@/types/api";

type UpdateDoctor = (args: { id: string; input: DoctorUpdateInput }) => Promise<unknown>;

/**
 * Booking eligibility is doctors ↔ services. Catalog steps no longer ask
 * the owner to tick those boxes — so any still-unlinked doctor is assigned
 * every current service. Specialties stay optional (discovery only) and
 * are not auto-linked. Existing links are left alone.
 */
export async function ensureDoctorCatalogLinks({
  doctors,
  specialties,
  services,
  updateDoctor,
  kind,
}: {
  doctors: Doctor[];
  specialties: Specialty[];
  services: Service[];
  updateDoctor: UpdateDoctor;
  kind: "specialties" | "services" | "both";
}) {
  const specialtyIds = specialties.map((s) => s.id);
  const serviceIds = services.map((s) => s.id);
  const patches = doctors.flatMap((doctor) => {
    const input: DoctorUpdateInput = {};
    if (
      (kind === "specialties" || kind === "both") &&
      specialtyIds.length > 0 &&
      doctor.specialty_ids.length === 0
    ) {
      input.specialty_ids = specialtyIds;
    }
    if (
      (kind === "services" || kind === "both") &&
      serviceIds.length > 0 &&
      doctor.service_ids.length === 0
    ) {
      input.service_ids = serviceIds;
    }
    if (!input.specialty_ids && !input.service_ids) return [];
    return [{ id: doctor.id, input }];
  });
  if (patches.length === 0) return;
  await Promise.all(patches.map((patch) => updateDoctor(patch)));
}
