from django.contrib import admin

from apps.knowledge.models import Document, KnowledgeChunk


class KnowledgeChunkInline(admin.TabularInline):
    model = KnowledgeChunk
    extra = 0
    fields = ("chunk_number", "page_number", "content", "token_count", "embedding_model")
    readonly_fields = ("chunk_number",)
    show_change_link = True


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "clinic",
        "file_type",
        "status",
        "chunk_count",
        "is_deleted",
        "created_at",
    )
    list_filter = ("status", "file_type", "is_deleted", "clinic")
    search_fields = ("title", "file_name")
    inlines = [KnowledgeChunkInline]


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "chunk_number",
        "page_number",
        "clinic",
        "embedding_model",
        "token_count",
    )
    list_filter = ("clinic", "embedding_model")
    search_fields = ("content", "document__title")
