"""Switch knowledge chunk embeddings from vector(1536) to vector(768) for local BGE."""

from django.db import migrations
import pgvector.django.vector


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0006_chunk_structure_metadata"),
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
            sql="UPDATE knowledge_chunks SET embedding = NULL WHERE embedding IS NOT NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="knowledgechunk",
            name="embedding",
            field=pgvector.django.vector.VectorField(
                blank=True,
                dimensions=768,
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
