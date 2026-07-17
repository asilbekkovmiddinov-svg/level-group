from sqlalchemy import text

from app.core.database import engine, SessionLocal
from app.crud.coin_credentials import store_credentials
from app.models.coin_credential import CoinOrderCredential
from app.models.wheel import WheelCoinOrder


def run_coin_chat_migration() -> None:
    """Additive, isolated schema changes for Coin Order Chat."""
    with engine.begin() as connection:
        connection.execute(text("""ALTER TABLE orders ADD COLUMN IF NOT EXISTS platform VARCHAR(20);"""))
        for table in ("orders", "wheel_coin_orders"):
            connection.execute(text(f"""ALTER TABLE {table}
                ADD COLUMN IF NOT EXISTS coin_notification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                ADD COLUMN IF NOT EXISTS coin_notification_message_id VARCHAR(100),
                ADD COLUMN IF NOT EXISTS coin_notification_attempts INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS coin_notification_last_error VARCHAR(255),
                ADD COLUMN IF NOT EXISTS coin_notification_sent_at TIMESTAMP WITH TIME ZONE,
                ADD COLUMN IF NOT EXISTS otp_notification_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                ADD COLUMN IF NOT EXISTS otp_notification_message_id VARCHAR(100),
                ADD COLUMN IF NOT EXISTS otp_notification_attempts INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS otp_notification_last_error VARCHAR(255),
                ADD COLUMN IF NOT EXISTS otp_notification_attempted_at TIMESTAMP WITH TIME ZONE,
                ADD COLUMN IF NOT EXISTS otp_notification_sent_at TIMESTAMP WITH TIME ZONE;"""))
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

    db = SessionLocal()
    try:
        for order in db.query(WheelCoinOrder).filter(WheelCoinOrder.konami_login.isnot(None)).with_for_update().all():
            exists = db.query(CoinOrderCredential).filter_by(order_type="WHEEL", order_id=order.id).first()
            if not exists and order.konami_password:
                store_credentials(db, "WHEEL", order.id, order.konami_login, order.konami_password)
            order.konami_login = None
            order.konami_password = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
