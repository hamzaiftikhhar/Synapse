"""Add full-text search index on knowledge chunk content."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS idx_kc_content_fts
                ON knowledge_chunks
                USING gin (to_tsvector('english', content));
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_kc_content_fts;",
        ),
    ]
