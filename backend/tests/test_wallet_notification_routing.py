from pathlib import Path


def test_backend_wallet_notifications_use_new_orders_channel_contract():
    root = Path(__file__).parents[1] / "app"
    config_source = (root / "core" / "config.py").read_text()
    transport_source = (root / "services" / "telegram_notifications.py").read_text()
    assert 'os.getenv("NEW_ORDERS_CHANNEL_ID")' in config_source
    assert "config.NEW_ORDERS_CHANNEL_ID" in transport_source
    assert "ADMIN_DEPOSIT_CHANNEL_ID" not in transport_source
