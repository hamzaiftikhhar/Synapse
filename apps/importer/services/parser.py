"""Turn an uploaded file into (headers, rows) — nothing else.

Deliberately dumb: no mapping, no validation beyond structural limits, no
LLM calls. Bounded by IMPORTER_MAX_* settings so a huge/malformed file
fails cheaply and predictably before any LLM cost is incurred.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

SUPPORTED_FILE_TYPES = {"csv", "xlsx"}


class ParserError(Exception):
    """Uploaded file could not be parsed, or exceeded a configured limit."""


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[dict[str, str]]


def detect_file_type(file_name: str) -> str:
    ext = Path(file_name or "").suffix.lower().lstrip(".")
    if ext not in SUPPORTED_FILE_TYPES:
        raise ParserError(
            f"Unsupported file type: {ext or 'unknown'}. "
            f"Supported: {', '.join(sorted(SUPPORTED_FILE_TYPES))}."
        )
    return ext


def _check_limits(headers: list[str], row_count: int) -> None:
    max_columns = getattr(settings, "IMPORTER_MAX_COLUMNS", 60)
    max_rows = getattr(settings, "IMPORTER_MAX_ROWS", 2000)
    if len(headers) > max_columns:
        raise ParserError(f"File has too many columns (max {max_columns}).")
    if row_count > max_rows:
        raise ParserError(f"File has too many rows (max {max_rows}).")


def parse_csv(raw_bytes: bytes) -> ParsedTable:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParserError("File is not valid UTF-8 text.") from exc

    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or []) if h and h.strip()]
    if not headers:
        raise ParserError("No columns found in file header row.")

    rows: list[dict[str, str]] = []
    for raw_row in reader:
        row = {
            header: (raw_row.get(header) or "").strip()
            for header in headers
        }
        # Skip fully-blank rows (trailing newlines, spacer rows) rather
        # than surfacing them as records with nothing mapped.
        if any(row.values()):
            rows.append(row)

    _check_limits(headers, len(rows))
    return ParsedTable(headers=headers, rows=rows)


def parse_xlsx(raw_bytes: bytes) -> ParsedTable:
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        # read_only avoids loading the whole workbook into memory; data_only
        # reads cached formula *results* rather than formula source — this
        # file is never evaluated/executed, only its stored values are read.
        workbook = openpyxl.load_workbook(
            io.BytesIO(raw_bytes), read_only=True, data_only=True
        )
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile) as exc:
        raise ParserError("File is not a valid .xlsx workbook.") from exc

    try:
        sheet = workbook.worksheets[0]
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise ParserError("No columns found in file header row.") from None

        headers = [str(h).strip() for h in header_row if h is not None and str(h).strip()]
        if not headers:
            raise ParserError("No columns found in file header row.")

        rows: list[dict[str, str]] = []
        for raw_row in rows_iter:
            row = {}
            for index, header in enumerate(headers):
                value = raw_row[index] if index < len(raw_row) else None
                row[header] = "" if value is None else str(value).strip()
            if any(row.values()):
                rows.append(row)
    finally:
        workbook.close()

    _check_limits(headers, len(rows))
    return ParsedTable(headers=headers, rows=rows)


def parse_file(*, file_name: str, raw_bytes: bytes) -> ParsedTable:
    file_type = detect_file_type(file_name)
    max_size = getattr(settings, "IMPORTER_MAX_FILE_SIZE_BYTES", 5 * 1024 * 1024)
    if len(raw_bytes) > max_size:
        raise ParserError(f"File is too large (max {max_size // (1024 * 1024)}MB).")

    if file_type == "csv":
        return parse_csv(raw_bytes)
    if file_type == "xlsx":
        return parse_xlsx(raw_bytes)
    raise ParserError(f"Unsupported file type: {file_type}.")  # pragma: no cover
