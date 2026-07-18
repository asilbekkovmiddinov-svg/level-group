import importlib.util
from pathlib import Path

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260718_orders_telegram_id_bigint.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("orders_telegram_id_bigint", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Inspector:
    def __init__(self):
        self.column_type = sa.Integer()

    def get_columns(self, table):
        assert table == "orders"
        return [{"name": "telegram_id", "type": self.column_type}]

    def get_indexes(self, table):
        assert table == "orders"
        return [
            {"name": "ix_orders_telegram_id"},
            {"name": "uq_order_user_idempotency"},
        ]

    def get_unique_constraints(self, table):
        assert table == "orders"
        return [{"name": "uq_order_user_idempotency"}]


def test_upgrade_widens_only_orders_telegram_id_and_preserves_dependencies(monkeypatch):
    migration = load_migration()
    inspector = Inspector()
    calls = []
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    def alter_column(table, column, **options):
        calls.append((table, column, options))
        inspector.column_type = sa.BigInteger()

    monkeypatch.setattr(migration.op, "alter_column", alter_column)
    migration.upgrade()

    assert len(calls) == 1
    table, column, options = calls[0]
    assert (table, column) == ("orders", "telegram_id")
    assert isinstance(options["existing_type"], sa.Integer)
    assert isinstance(options["type_"], sa.BigInteger)
    assert options["postgresql_using"] == "telegram_id::BIGINT"


def test_upgrade_is_idempotent_when_column_is_already_bigint(monkeypatch):
    migration = load_migration()
    inspector = Inspector()
    inspector.column_type = sa.BigInteger()
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not alter")),
    )
    migration.upgrade()
