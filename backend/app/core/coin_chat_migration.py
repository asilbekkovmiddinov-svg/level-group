from sqlalchemy import text

from app.core.database import engine


def run_coin_chat_migration() -> None:
    """Additive, isolated schema changes for Coin Order Chat."""
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS coin_order_messages (
                id SERIAL PRIMARY KEY, order_type VARCHAR(10) NOT NULL,
                order_id INTEGER NOT NULL, telegram_id BIGINT NOT NULL,
                sender VARCHAR(10) NOT NULL, sender_id BIGINT,
                message TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                read_at TIMESTAMP WITH TIME ZONE
            );
        """))
        connection.execute(text("""CREATE INDEX IF NOT EXISTS ix_coin_order_messages_order
            ON coin_order_messages (order_type, order_id, id);"""))
        connection.execute(text("""CREATE INDEX IF NOT EXISTS ix_coin_order_messages_telegram_id
            ON coin_order_messages (telegram_id);"""))
