"""Doctor creation — shared by apps/api/doctors/router.py and the
importer commit path (apps/importer/services/committer.py)."""

from apps.clinics.models import Clinic
from apps.doctors.models import Doctor


def create_doctor(
    *,
    clinic: Clinic,
    full_name: str,
    title: str = "",
    bio: str = "",
    photo_url: str = "",
    languages: list[str] | None = None,
    is_active: bool = True,
    is_accepting_patients: bool = True,
) -> Doctor:
    return Doctor.objects.create(
        clinic=clinic,
        full_name=full_name,
        title=title,
        bio=bio,
        photo_url=photo_url,
        languages=list(languages) if languages is not None else [],
        is_active=is_active,
        is_accepting_patients=is_accepting_patients,
    )
