# Generated manually to alter ttl column from integer to timestamp

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            # PostgreSQL: Alter the column type from integer to timestamp (only if currently integer)
            sql="""
                DO $$
                BEGIN
                    -- Check if ttl column is integer type
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'tmpl_api_auth' 
                        AND column_name = 'ttl' 
                        AND data_type = 'integer'
                    ) THEN
                        -- Alter column from integer to timestamp
                        ALTER TABLE tmpl_api_auth 
                        ALTER COLUMN ttl TYPE TIMESTAMP WITH TIME ZONE 
                        USING CASE 
                            WHEN ttl = 0 THEN NULL
                            WHEN ttl > 0 THEN created_at + (ttl || ' seconds')::INTERVAL
                            ELSE NULL
                        END;
                    END IF;
                END $$;
            """,
            reverse_sql="""
                DO $$
                BEGIN
                    -- Check if ttl column is timestamp type
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'tmpl_api_auth' 
                        AND column_name = 'ttl' 
                        AND data_type = 'timestamp with time zone'
                    ) THEN
                        -- Alter column from timestamp to integer
                        ALTER TABLE tmpl_api_auth 
                        ALTER COLUMN ttl TYPE INTEGER 
                        USING CASE 
                            WHEN ttl IS NULL THEN 0
                            ELSE EXTRACT(EPOCH FROM (ttl - created_at))::INTEGER
                        END;
                    END IF;
                END $$;
            """
        ),
    ]
