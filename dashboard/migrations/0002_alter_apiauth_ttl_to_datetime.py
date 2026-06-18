# Converts ttl from integer → DateTimeField on PostgreSQL.
# On SQLite (fresh DB), 0001_initial already creates ttl as DateTimeField — no-op.

from django.db import migrations


def _pg_alter_forward(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tmpl_api_auth'
                AND column_name = 'ttl'
                AND data_type = 'integer'
            ) THEN
                ALTER TABLE tmpl_api_auth
                ALTER COLUMN ttl TYPE TIMESTAMP WITH TIME ZONE
                USING CASE
                    WHEN ttl = 0 THEN NULL
                    WHEN ttl > 0 THEN created_at + (ttl || ' seconds')::INTERVAL
                    ELSE NULL
                END;
            END IF;
        END $$;
    """)


def _pg_alter_reverse(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tmpl_api_auth'
                AND column_name = 'ttl'
                AND data_type = 'timestamp with time zone'
            ) THEN
                ALTER TABLE tmpl_api_auth
                ALTER COLUMN ttl TYPE INTEGER
                USING CASE
                    WHEN ttl IS NULL THEN 0
                    ELSE EXTRACT(EPOCH FROM (ttl - created_at))::INTEGER
                END;
            END IF;
        END $$;
    """)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(_pg_alter_forward, reverse_code=_pg_alter_reverse),
    ]
