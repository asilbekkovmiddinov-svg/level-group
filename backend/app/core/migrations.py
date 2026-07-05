from sqlalchemy import text

from app.core.database import engine


def run_migrations():
    with engine.begin() as connection:
        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS claimed_by BIGINT;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS approved_by BIGINT;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS rejected_by BIGINT;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS reject_reason VARCHAR(255);
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS processing_seconds INTEGER;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS card_number VARCHAR(32);
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS card_holder VARCHAR(120);
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS bank_name VARCHAR(120);
            """)
        )
