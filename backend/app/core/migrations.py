import logging

from sqlalchemy import bindparam, text

from app.core.database import engine
from app.models.match import LEGACY_MATCH_STATUS_MAPPING


logger = logging.getLogger(__name__)


def run_migrations():
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS receipt_orphans (
                id SERIAL PRIMARY KEY, object_key VARCHAR(500) NOT NULL UNIQUE,
                attempts INTEGER NOT NULL DEFAULT 0, last_error VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))

        # =========================
        # WITHDRAWS
        # =========================

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS claimed_by BIGINT;
        """))

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128),
            ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(64);
        """))
        connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_withdraw_user_idempotency
            ON withdraws (telegram_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
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

        connection.execute(text("""
            ALTER TABLE withdraws
            ADD COLUMN IF NOT EXISTS notification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS notification_message_id VARCHAR(100),
            ADD COLUMN IF NOT EXISTS notification_attempts INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS notification_last_error VARCHAR(255),
            ADD COLUMN IF NOT EXISTS notification_last_attempt_at TIMESTAMP WITH TIME ZONE;
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

        connection.execute(text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS last_name VARCHAR(100);
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
        connection.execute(text("""
            ALTER TABLE deposits
            ADD COLUMN IF NOT EXISTS receipt_revision INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS claimed_receipt_revision INTEGER,
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128),
            ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(64);
        """))
        connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_deposit_user_idempotency
            ON deposits (telegram_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
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
                game_type VARCHAR(32) NOT NULL DEFAULT 'EFOOTBALL',
                scheduled_at TIMESTAMP WITH TIME ZONE NOT NULL,
                ready_check_started_at TIMESTAMP WITH TIME ZONE,
                ready_check_deadline_at TIMESTAMP WITH TIME ZONE,
                ready_window_started_at TIMESTAMP WITH TIME ZONE,
                ready_deadline_at TIMESTAMP WITH TIME ZONE,
                creator_ready BOOLEAN NOT NULL DEFAULT FALSE,
                opponent_ready BOOLEAN NOT NULL DEFAULT FALSE,
                creator_ready_at TIMESTAMP WITH TIME ZONE,
                opponent_ready_at TIMESTAMP WITH TIME ZONE,
                creator_rules_accepted_at TIMESTAMP WITH TIME ZONE,
                opponent_rules_accepted_at TIMESTAMP WITH TIME ZONE,
                room_code VARCHAR(64),
                room_code_created_by BIGINT,
                room_code_created_at TIMESTAMP WITH TIME ZONE,
                creator_result_screenshot VARCHAR(500),
                opponent_result_screenshot VARCHAR(500),
                creator_result_uploaded_at TIMESTAMP WITH TIME ZONE,
                opponent_result_uploaded_at TIMESTAMP WITH TIME ZONE,
                creator_result_video VARCHAR(500),
                opponent_result_video VARCHAR(500),
                creator_result_video_uploaded_at TIMESTAMP WITH TIME ZONE,
                opponent_result_video_uploaded_at TIMESTAMP WITH TIME ZONE,
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

        # Arena V2 foundation: these additions are nullable where they model
        # future flow steps, so existing rows remain valid during rollout.
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS game_type VARCHAR(32) NOT NULL DEFAULT 'EFOOTBALL';
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS creator_rules_accepted_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS opponent_rules_accepted_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS ready_window_started_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS ready_deadline_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS creator_result_video VARCHAR(500);
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS opponent_result_video VARCHAR(500);
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS creator_result_video_uploaded_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS opponent_result_video_uploaded_at TIMESTAMP WITH TIME ZONE;
        """))
        connection.execute(text("""
            ALTER TABLE matches
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128),
            ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR(64);
        """))
        connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_match_creator_idempotency
            ON matches (creator_telegram_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        """))

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS arena_notification_deliveries (
                id SERIAL PRIMARY KEY,
                match_id INTEGER NOT NULL REFERENCES matches(id),
                event_type VARCHAR(32) NOT NULL,
                recipient_telegram_id BIGINT NOT NULL,
                dedup_key VARCHAR(255) NOT NULL UNIQUE,
                status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0,
                message_id VARCHAR(64),
                last_error TEXT,
                last_attempt_at TIMESTAMP WITH TIME ZONE,
                sent_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
            );
        """))
        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_arena_notification_deliveries_match_id
            ON arena_notification_deliveries (match_id);
        """))
        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_arena_notification_deliveries_status
            ON arena_notification_deliveries (status);
        """))

        # Earlier SQLAlchemy-created databases can use a native enum. Convert
        # only that column to VARCHAR before storing new target state values.
        connection.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'matches'
                      AND column_name = 'status'
                      AND data_type = 'USER-DEFINED'
                ) THEN
                    ALTER TABLE matches
                    ALTER COLUMN status TYPE VARCHAR(30) USING status::text;
                END IF;
            END $$;
        """))

        known_legacy_statuses = tuple(LEGACY_MATCH_STATUS_MAPPING)
        target_statuses = tuple(set(LEGACY_MATCH_STATUS_MAPPING.values()))
        unknown_status_count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM matches
                WHERE status NOT IN :known_legacy_statuses
                  AND status NOT IN :target_statuses
            """).bindparams(
                bindparam("known_legacy_statuses", expanding=True),
                bindparam("target_statuses", expanding=True),
            ),
            {
                "known_legacy_statuses": known_legacy_statuses,
                "target_statuses": target_statuses,
            },
        ).scalar_one()
        if unknown_status_count:
            logger.warning(
                "Arena V2 migration retained %s unrecognized match status row(s).",
                unknown_status_count,
            )

        for legacy_status, target_status in LEGACY_MATCH_STATUS_MAPPING.items():
            if legacy_status == target_status:
                continue
            connection.execute(
                text("""
                    UPDATE matches
                    SET status = :target_status,
                        updated_at = NOW()
                    WHERE status = :legacy_status
                """),
                {"legacy_status": legacy_status, "target_status": target_status},
            )

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
