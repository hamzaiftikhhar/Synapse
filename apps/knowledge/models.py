"""Documents and knowledge chunks with pgvector embeddings."""

from django.db import models
from django.db.models import Q
from pgvector.django import HnswIndex, VectorField

from core.models import SoftDeleteModel, TenantModel, TimestampedModel


class DocumentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    INDEXED = "indexed", "Indexed"
    FAILED = "failed", "Failed"


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
    chunk_count = models.PositiveIntegerField(default=0)
    # Nullable until clinic admin users exist (Phase 4/8)
    uploaded_by = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
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
    page_number = models.PositiveIntegerField(null=True, blank=True)
    content = models.TextField()
    token_count = models.PositiveIntegerField(null=True, blank=True)
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    embedding_model = models.CharField(
        max_length=50,
        default="text-embedding-3-small",
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
