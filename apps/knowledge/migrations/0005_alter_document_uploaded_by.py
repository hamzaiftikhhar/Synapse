# Generated manually — UUID uploaded_by cannot cast to bigint User FK.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0004_remove_document_documents_clinic__ebdf1e_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name="document",
            name="uploaded_by",
        ),
        migrations.AddField(
            model_name="document",
            name="uploaded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="uploaded_documents",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
