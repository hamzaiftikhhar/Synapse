"""Switch knowledge chunk embeddings from vector(768) BGE to vector(1536) OpenAI."""

from django.db import migrations
import pgvector.django.vector


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0009_document_processing_stage"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_kc_embedding_hnsw;",
            reverse_sql="""
                CREATE INDEX IF NOT EXISTS idx_kc_embedding_hnsw
                ON knowledge_chunks
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """,
        ),
        migrations.RunSQL(
            sql="""
                UPDATE knowledge_chunks SET embedding = NULL, embedding_model = ''
                WHERE embedding IS NOT NULL OR embedding_model <> '';
                UPDATE documents
                SET status = 'chunked', processing_stage = 'chunking'
                WHERE status = 'indexed' AND is_deleted = false;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="knowledgechunk",
            name="embedding",
            field=pgvector.django.vector.VectorField(
                blank=True,
                dimensions=1536,
                null=True,
            ),
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS idx_kc_embedding_hnsw
                ON knowledge_chunks
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_kc_embedding_hnsw;",
        ),
    ]
