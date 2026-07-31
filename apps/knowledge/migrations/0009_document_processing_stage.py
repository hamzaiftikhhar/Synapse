# Generated for Document.processing_stage + cancelled status

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0008_document_routing_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="processing_stage",
            field=models.CharField(
                blank=True,
                choices=[
                    ("queued", "Queued"),
                    ("uploading", "Uploading"),
                    ("extracting", "Extracting text"),
                    ("chunking", "Chunking document"),
                    ("embedding", "Generating embeddings"),
                    ("storing", "Storing knowledge"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                default="queued",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="document",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("chunked", "Chunked"),
                    ("indexed", "Indexed"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
