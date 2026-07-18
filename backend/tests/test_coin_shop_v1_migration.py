from pathlib import Path


def test_order_number_migration_is_unique_and_non_destructive():
    source = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260718_coin_shop_order_number.py"
    ).read_text()
    assert 'sa.Column("order_number", sa.String(8)' in source
    assert '"ix_orders_order_number"' in source
    assert "unique=True" in source
    assert "ROW_NUMBER() OVER (ORDER BY id)" in source
    assert "DROP COLUMN" not in source


def test_shop_runtime_has_no_credential_details_or_order_chat_contract():
    root = Path(__file__).parents[1] / "app"
    schema = (root / "schemas" / "order.py").read_text()
    chat = (root / "crud" / "coin_order_chat.py").read_text()
    order = (root / "crud" / "order.py").read_text()
    order_model = (root / "models" / "order.py").read_text()
    assert "konami_login" not in schema
    assert "konami_password" not in schema
    assert 'ORDER_MODELS = {"WHEEL": WheelCoinOrder}' in chat
    assert 'prepare_operator_wait(db, "SHOP"' not in order
    assert "otp_notification_status" not in order_model
