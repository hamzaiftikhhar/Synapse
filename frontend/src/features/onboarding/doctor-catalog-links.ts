import type { Doctor, DoctorUpdateInput, Service, Specialty } from "@/types/api";

type UpdateDoctor = (args: { id: string; input: DoctorUpdateInput }) => Promise<unknown>;

/**
 * Booking eligibility is doctors ↔ services — attaching every service to
 * every doctor by default is only safe when there's exactly one doctor to
 * attach them to (nothing to disambiguate). For 2+ doctors this used to
 * blanket-link regardless, which is how "Cardiology consultation" ended up
 * bookable with a neurologist. With 2+ doctors, onboarding now asks the
 * owner to explicitly assign (see specialties-step.tsx / services-step.tsx)
 * instead of guessing. Existing links are left alone either way.
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
  if (doctors.length > 1) return;
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
