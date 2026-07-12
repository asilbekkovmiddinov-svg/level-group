from sqlalchemy import text

from app.core.database import engine


def run_migrations():
    with engine.begin() as connection:

        # =========================
        # WITHDRAWS
        # =========================

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS claimed_by BIGINT;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS approved_by BIGINT;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS rejected_by BIGINT;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS reject_reason VARCHAR(255);
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS processing_seconds INTEGER;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS card_number VARCHAR(32);
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS card_holder VARCHAR(120);
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS bank_name VARCHAR(120);
        """))

        # =========================
        # P2P ORDERS
        # =========================

        connection.execute(text("""
            ALTER TABLE p2p_orders
            ADD COLUMN IF NOT EXISTS response_minutes INTEGER DEFAULT 15 NOT NULL;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_orders
            ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(255);
        """))

        # =========================
        # P2P TRADES
        # =========================

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS owner_expires_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS requester_expires_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS timeout_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS timeout_stage VARCHAR(30);
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(255);
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS owner_status VARCHAR(20) DEFAULT 'PENDING';
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS requester_status VARCHAR(20) DEFAULT 'PENDING';
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE p2p_trades
            ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE;
        """))

        # =========================
        # USERS
        # =========================

        connection.execute(text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE;
        """))

        # =========================
        # DEPOSITS
        # =========================

        connection.execute(text("""
            ALTER TABLE deposits
            ADD COLUMN IF NOT EXISTS approved_by BIGINT;
        """))

        connection.execute(text("""
            ALTER TABLE deposits
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP WITH TIME ZONE;
        """))

        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_object_key VARCHAR(500);
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_content_type VARCHAR(100);
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_size INTEGER;
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_uploaded_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_notification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING';
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_notification_sent_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_notification_message_id VARCHAR(100);
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_notification_attempts INTEGER NOT NULL DEFAULT 0;
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_notification_last_error VARCHAR(255);
        """))
        connection.execute(text("""
            ALTER TABLE deposits ADD COLUMN IF NOT EXISTS receipt_notification_last_attempt_at TIMESTAMP WITH TIME ZONE;
        """))

        # =========================
        # PRODUCTS
        # =========================

        connection.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS description VARCHAR(255);
        """))

        connection.execute(text("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS order_index INTEGER DEFAULT 0;
        """))

        # =========================
        # ORDERS
        # =========================

        connection.execute(text("""
            ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS region VARCHAR(100);
        """))

        # =========================
        # 1VS1 ARENA MATCHES
        # =========================

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS matches (
                id SERIAL PRIMARY KEY,
                creator_telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
                opponent_telegram_id BIGINT REFERENCES users(telegram_id),
                efc_amount NUMERIC(18, 2) NOT NULL,
                total_pool NUMERIC(18, 2) NOT NULL DEFAULT 0,
                commission_amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
                winner_reward NUMERIC(18, 2) NOT NULL DEFAULT 0,
                status VARCHAR(30) NOT NULL DEFAULT 'WAITING_PLAYER',
                scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
                ready_check_started_at TIMESTAMP WITH TIME ZONE,
                ready_check_deadline_at TIMESTAMP WITH TIME ZONE,
                creator_ready BOOLEAN NOT NULL DEFAULT FALSE,
                opponent_ready BOOLEAN NOT NULL DEFAULT FALSE,
                creator_ready_at TIMESTAMP WITH TIME ZONE,
                opponent_ready_at TIMESTAMP WITH TIME ZONE,
                room_code VARCHAR(64),
                room_code_created_by BIGINT,
                room_code_created_at TIMESTAMP WITH TIME ZONE,
                creator_result_screenshot VARCHAR(500),
                opponent_result_screenshot VARCHAR(500),
                creator_result_uploaded_at TIMESTAMP WITH TIME ZONE,
                opponent_result_uploaded_at TIMESTAMP WITH TIME ZONE,
                winner_telegram_id BIGINT,
                loser_telegram_id BIGINT,
                result_type VARCHAR(30),
                admin_telegram_id BIGINT,
                admin_comment TEXT,
                resolved_at TIMESTAMP WITH TIME ZONE,
                cancel_reason TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
            );
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_matches_creator_telegram_id
            ON matches (creator_telegram_id);
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_matches_opponent_telegram_id
            ON matches (opponent_telegram_id);
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_matches_status
            ON matches (status);
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_matches_scheduled_at
            ON matches (scheduled_at);
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_matches_winner_telegram_id
            ON matches (winner_telegram_id);
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_matches_loser_telegram_id
            ON matches (loser_telegram_id);
        """))

        # =========================
        # 1VS1 ARENA STATS
        # =========================

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS match_stats (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL UNIQUE REFERENCES users(telegram_id),
                total_matches INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                win_rate NUMERIC(5, 2) NOT NULL DEFAULT 0,
                win_streak INTEGER NOT NULL DEFAULT 0,
                best_win_streak INTEGER NOT NULL DEFAULT 0,
                total_efc_won NUMERIC(18, 2) NOT NULL DEFAULT 0,
                total_efc_lost NUMERIC(18, 2) NOT NULL DEFAULT 0,
                biggest_win NUMERIC(18, 2) NOT NULL DEFAULT 0,
                rating INTEGER NOT NULL DEFAULT 1000,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
            );
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_match_stats_telegram_id
            ON match_stats (telegram_id);
        """))

        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_match_stats_rating
            ON match_stats (rating);
        """))
