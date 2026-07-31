# Generated manually for Document routing_summary / routing_keywords

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0007_embedding_dimensions_768"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="routing_summary",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="document",
            name="routing_keywords",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
