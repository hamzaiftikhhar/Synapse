"""Save/resolve uploaded import files on disk — same shape as
apps/knowledge/services/storage.py, kept separate since import files live
under a different media path and are deleted whenever a non-committed job
is deleted (knowledge documents are soft-deleted; these aren't)."""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile


class StorageError(Exception):
    pass


def save_upload(*, clinic_id: uuid.UUID, uploaded_file: UploadedFile) -> tuple[str, int]:
    safe_name = Path(uploaded_file.name or "upload.bin").name
    relative_path = f"clinics/{clinic_id}/imports/{uuid.uuid4()}/{safe_name}"
    absolute = Path(settings.MEDIA_ROOT) / relative_path

    try:
        absolute.parent.mkdir(parents=True, exist_ok=True)
        with absolute.open("wb") as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)
    except OSError as exc:
        raise StorageError(f"Could not save file: {exc}") from exc

    size = uploaded_file.size if uploaded_file.size is not None else absolute.stat().st_size
    return relative_path, int(size)


def absolute_path(relative_path: str) -> Path:
    return Path(settings.MEDIA_ROOT) / relative_path


def delete_file(relative_path: str) -> None:
    path = absolute_path(relative_path)
    if path.is_file():
        path.unlink(missing_ok=True)
