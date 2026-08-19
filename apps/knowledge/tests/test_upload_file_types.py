"""document_service.upload_document now accepts CSV/XLSX alongside PDF —
this only checks the accept/reject boundary and the stored file_type,
not the full async ingestion pipeline (covered by test_extract_tabular.py
and the pre-existing chunking/embedding tests)."""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.clinics.models import Clinic
from apps.knowledge.models import Document
from apps.knowledge.services.document_service import DocumentServiceError, upload_document


class UploadFileTypeTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="upload-types-clinic", name="Upload Types Clinic",
            email="owner@upload-types.example.com",
        )

    def _upload(self, name: str, content: bytes, content_type: str) -> Document:
        return upload_document(
            clinic=self.clinic,
            uploaded_file=SimpleUploadedFile(name, content, content_type=content_type),
            run_ingestion=False,
        )

    def test_csv_is_accepted(self):
        doc = self._upload("faq.csv", b"Question,Answer\nQ1,A1\n", "text/csv")
        self.assertEqual(doc.file_type, "csv")

    def test_xlsx_is_accepted(self):
        import io

        import openpyxl

        wb = openpyxl.Workbook()
        wb.active.append(["Question", "Answer"])
        buf = io.BytesIO()
        wb.save(buf)
        doc = self._upload(
            "faq.xlsx", buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(doc.file_type, "xlsx")

    def test_pdf_still_accepted(self):
        # Minimal-but-valid-enough-to-store PDF header — upload_document
        # itself never parses the file, only the async ingestion path does.
        doc = self._upload("handbook.pdf", b"%PDF-1.4 fake", "application/pdf")
        self.assertEqual(doc.file_type, "pdf")

    def test_unsupported_type_still_rejected(self):
        with self.assertRaises(DocumentServiceError) as ctx:
            self._upload("notes.docx", b"binary content", "application/msword")
        message = str(ctx.exception)
        self.assertIn("docx", message)
        self.assertIn("PDF", message)
        self.assertIn("CSV", message)
        self.assertIn("XLSX", message)

    def test_legacy_xls_is_not_supported(self):
        """Deliberate scope decision, matching apps.importer's own — see
        extract.py's comment on why a second Excel library isn't added."""
        with self.assertRaises(DocumentServiceError):
            self._upload("old.xls", b"binary", "application/vnd.ms-excel")
