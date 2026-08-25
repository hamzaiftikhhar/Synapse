"""Documents and knowledge chunks with pgvector embeddings."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from pgvector.django import HnswIndex, VectorField

from core.models import SoftDeleteModel, TenantModel, TimestampedModel


class DocumentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    CHUNKED = "chunked", "Chunked"  # text chunks saved; embeddings not yet
    INDEXED = "indexed", "Indexed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class ProcessingStage(models.TextChoices):
    QUEUED = "queued", "Queued"
    UPLOADING = "uploading", "Uploading"
    EXTRACTING = "extracting", "Extracting text"
    CHUNKING = "chunking", "Chunking document"
    EMBEDDING = "embedding", "Generating embeddings"
    STORING = "storing", "Storing knowledge"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class ChunkType(models.TextChoices):
    PARAGRAPH = "paragraph", "Paragraph"
    LIST = "list", "List"
    HEADING = "heading", "Heading"
    MIXED = "mixed", "Mixed"


class Document(TenantModel, TimestampedModel, SoftDeleteModel):
    title = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    storage_path = models.CharField(max_length=500)
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDING,
    )
    processing_stage = models.CharField(
        max_length=32,
        choices=ProcessingStage.choices,
        default=ProcessingStage.QUEUED,
        blank=True,
    )
    chunk_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    metadata = models.JSONField(default=dict, blank=True)
    # Compact signals for Small NLU vector gating (2–3 sentences + keywords)
    routing_summary = models.TextField(blank=True, default="")
    routing_keywords = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "documents"
        indexes = [
            models.Index(
                fields=["clinic", "status"],
                name="idx_docs_status_live",
                condition=Q(is_deleted=False),
            ),
            models.Index(
                fields=["clinic", "created_at"],
                name="idx_docs_created_live",
                condition=Q(is_deleted=False),
            ),
        ]

    def __str__(self) -> str:
        return self.title


class KnowledgeChunk(TenantModel):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_number = models.PositiveIntegerField()
    # Legacy single-page field — kept in sync with page_start for older callers
    page_number = models.PositiveIntegerField(null=True, blank=True)
    page_start = models.PositiveIntegerField(null=True, blank=True)
    page_end = models.PositiveIntegerField(null=True, blank=True)
    heading = models.CharField(max_length=500, blank=True, default="")
    chunk_type = models.CharField(
        max_length=20,
        choices=ChunkType.choices,
        default=ChunkType.PARAGRAPH,
    )
    content = models.TextField()
    token_count = models.PositiveIntegerField(null=True, blank=True)
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    embedding_model = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "knowledge_chunks"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_number"],
                name="uq_chunk_document_number",
            ),
        ]
        indexes = [
            models.Index(fields=["clinic", "document"]),
            models.Index(fields=["document", "page_number"]),
            models.Index(fields=["document", "page_start"]),
            HnswIndex(
                name="idx_kc_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"Chunk {self.chunk_number} of {self.document.title}"
