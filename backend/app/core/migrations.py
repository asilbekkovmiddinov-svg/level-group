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

        connection.execute(
            text("""
            ALTER TABLE p2p_orders
            ADD COLUMN IF NOT EXISTS response_minutes INTEGER DEFAULT 15 NOT NULL;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_orders
            ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(255);
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS owner_expires_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS requester_expires_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS timeout_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS timeout_stage VARCHAR(30);
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(255);
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS owner_status VARCHAR(20) DEFAULT 'PENDING';
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS requester_status VARCHAR(20) DEFAULT 'PENDING';
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE;
            """)
        )

        connection.execute(
            text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE;
            """)
        )
