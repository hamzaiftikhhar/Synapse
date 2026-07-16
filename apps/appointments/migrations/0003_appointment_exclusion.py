"""Add appointment exclusion constraint and knowledge chunk FTS index."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("appointments", "0002_initial"),
        ("knowledge", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE appointments
                ADD CONSTRAINT excl_appointments_no_overlap
                EXCLUDE USING gist (
                    doctor_id WITH =,
                    tstzrange(start_time, end_time) WITH &&
                )
                WHERE (status NOT IN ('cancelled', 'rescheduled'));
            """,
            reverse_sql="""
                ALTER TABLE appointments
                DROP CONSTRAINT IF EXISTS excl_appointments_no_overlap;
            """,
        ),
    ]
