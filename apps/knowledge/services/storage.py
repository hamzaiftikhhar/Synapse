"""Save and resolve clinic document files on disk.

Why this file exists
--------------------
Upload must not mix HTTP, database, and filesystem concerns.
This module only cares about writing bytes to MEDIA_ROOT and
returning a relative path we store on Document.storage_path.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile


class StorageError(Exception):
    """File could not be written or read."""


def save_upload(*, clinic_id: uuid.UUID, uploaded_file: UploadedFile) -> tuple[str, int]:
    """
    Persist an uploaded file under media/clinics/<clinic_id>/documents/<uuid>/.

    Returns
    -------
    relative_path : str
        Path relative to MEDIA_ROOT (stored on Document.storage_path).
    size_bytes : int
        File size for Document.file_size_bytes.
    """
    safe_name = Path(uploaded_file.name or "upload.bin").name
    relative_path = f"clinics/{clinic_id}/documents/{uuid.uuid4()}/{safe_name}"
    absolute_path = Path(settings.MEDIA_ROOT) / relative_path

    try:
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        with absolute_path.open("wb") as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)
    except OSError as exc:
        raise StorageError(f"Could not save file: {exc}") from exc

    size = uploaded_file.size if uploaded_file.size is not None else absolute_path.stat().st_size
    return relative_path, int(size)


def absolute_path(relative_path: str) -> Path:
    """Resolve Document.storage_path to a full filesystem path."""
    return Path(settings.MEDIA_ROOT) / relative_path


def file_exists(relative_path: str) -> bool:
    return absolute_path(relative_path).is_file()
