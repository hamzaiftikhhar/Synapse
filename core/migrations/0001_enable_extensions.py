"""
Enable PostgreSQL extensions required by Synapse.

- pgcrypto: gen_random_uuid()
- vector:   pgvector embeddings (Phase 3+)
- btree_gist: appointment exclusion constraints (Phase 3+)
"""

from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        CreateExtension("pgcrypto"),
        CreateExtension("vector"),
        CreateExtension("btree_gist"),
    ]
