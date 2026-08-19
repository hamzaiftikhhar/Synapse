"""CSV/XLSX extraction into the same PageText shape PDF extraction already
produces — proves the rest of the pipeline (clean/chunk/embed) needs no
changes, and reuses apps.importer's parser rather than a second copy."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.knowledge.pipeline.extract import ExtractionError, extract_pages


class CsvExtractionTests(SimpleTestCase):
    def _write(self, content: bytes, suffix: str = ".csv") -> Path:
        f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        f.write(content)
        f.close()
        path = Path(f.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_rows_become_readable_text_blocks(self):
        path = self._write(
            b"Question,Answer\nWhat are your hours?,9-5 Mon-Fri\nDo you take walk-ins?,Yes\n"
        )
        pages = extract_pages(file_path=path, file_type="csv")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].page_number, 1)
        self.assertIn("Question: What are your hours?", pages[0].text)
        self.assertIn("Answer: 9-5 Mon-Fri", pages[0].text)
        self.assertIn("Do you take walk-ins?", pages[0].text)

    def test_empty_values_are_omitted_from_the_block(self):
        path = self._write(b"Question,Answer,Notes\nWhat are your hours?,9-5,\n")
        pages = extract_pages(file_path=path, file_type="csv")
        self.assertNotIn("Notes:", pages[0].text)

    def test_header_only_csv_raises_extraction_error(self):
        path = self._write(b"Question,Answer\n")
        with self.assertRaises(ExtractionError):
            extract_pages(file_path=path, file_type="csv")

    def test_malformed_encoding_raises_extraction_error_not_unicode_error(self):
        path = self._write(b"\xff\xfe\x00Question,Answer\n\x80\x81invalid")
        with self.assertRaises(ExtractionError):
            extract_pages(file_path=path, file_type="csv")

    def test_missing_file_raises_extraction_error(self):
        with self.assertRaises(ExtractionError):
            extract_pages(file_path=Path("/tmp/does-not-exist-kb.csv"), file_type="csv")

    def test_unsupported_type_still_raises(self):
        path = self._write(b"hello", suffix=".txt")
        with self.assertRaises(ExtractionError):
            extract_pages(file_path=path, file_type="txt")


class XlsxExtractionTests(SimpleTestCase):
    def _write_xlsx(self, rows: list[list[str]]) -> Path:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)

        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        f.write(buf.getvalue())
        f.close()
        path = Path(f.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_rows_become_readable_text_blocks(self):
        path = self._write_xlsx(
            [["Question", "Answer"], ["What are your hours?", "9-5 Mon-Fri"]]
        )
        pages = extract_pages(file_path=path, file_type="xlsx")
        self.assertEqual(len(pages), 1)
        self.assertIn("Question: What are your hours?", pages[0].text)

    def test_invalid_xlsx_raises_extraction_error(self):
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        f.write(b"not a real xlsx file")
        f.close()
        path = Path(f.name)
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaises(ExtractionError):
            extract_pages(file_path=path, file_type="xlsx")
