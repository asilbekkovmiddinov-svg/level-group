from sqlalchemy import create_engine, inspect, text

import app.models
from app.core.arena_v3_migrations import (
    ARENA_V4_TABLES,
    run_arena_v3_migrations,
)
from app.models.arena_v3 import (
    ArenaV3Appeal,
    ArenaV3Match,
    ArenaV4AdminReview,
    ArenaV4ResultRevision,
    ArenaV4SettlementOperation,
    ArenaV4RewardHoldStatus,
)
from app.models.wallet import Wallet


def test_v4_models_expose_frozen_database_contract():
    assert {table.name for table in ARENA_V4_TABLES} == {
        "arena_admin_reviews",
        "arena_result_revisions",
        "arena_settlement_operations",
    }
    match_columns = ArenaV3Match.__table__.columns
    assert {
        "reward_hold_status",
        "reward_release_at",
        "appeal_deadline_at",
        "current_result_type",
        "result_version",
        "current_decision_id",
        "initial_decision_id",
    }.issubset(match_columns.keys())
    assert match_columns.reward_hold_status.default.arg == ArenaV4RewardHoldStatus.NONE
    assert ArenaV4AdminReview.__table__.columns.match_id.nullable is False
    assert ArenaV4ResultRevision.__table__.columns.version.nullable is False
    assert ArenaV4SettlementOperation.__table__.columns.idempotency_key.nullable is False
    assert Wallet.__table__.columns.locked_reward_efc.nullable is False


def test_appeal_model_allows_legacy_rows_but_has_v4_fields_and_one_per_match():
    columns = ArenaV3Appeal.__table__.columns
    assert {"reason", "submitted_at", "deadline_at"}.issubset(columns.keys())
    assert columns.video_storage_key.nullable is True
    constraints = {
        constraint.name for constraint in ArenaV3Appeal.__table__.constraints
    }
    assert "uq_arena_appeal_match" in constraints


def test_additive_v4_migration_is_idempotent_and_preserves_existing_match():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE arena_matches ("
            "id INTEGER PRIMARY KEY, public_id VARCHAR(32), status VARCHAR(32))"
        ))
        connection.execute(text(
            "INSERT INTO arena_matches (id, public_id, status) "
            "VALUES (1, 'LEGACY-ACTIVE', 'PLAYING')"
        ))
        connection.execute(text(
            "CREATE TABLE arena_appeals ("
            "id INTEGER PRIMARY KEY, match_id INTEGER, "
            "submitted_by BIGINT, reason_code VARCHAR(64) NOT NULL, "
            "video_storage_key VARCHAR(500), file_hash VARCHAR(64), "
            "created_at TIMESTAMP)"
        ))
        connection.execute(text(
            "CREATE TABLE wallets ("
            "telegram_id BIGINT PRIMARY KEY, efc_balance NUMERIC(18, 2), "
            "uzs_balance NUMERIC(18, 2), locked_efc NUMERIC(18, 2), "
            "locked_uzs NUMERIC(18, 2))"
        ))
        connection.execute(text(
            "INSERT INTO wallets VALUES (1001, 25, 0, 500, 0)"
        ))

    run_arena_v3_migrations(engine)
    run_arena_v3_migrations(engine)

    inspector = inspect(engine)
    assert {
        "arena_admin_reviews",
        "arena_result_revisions",
        "arena_settlement_operations",
    }.issubset(inspector.get_table_names())
    match_columns = {item["name"] for item in inspector.get_columns("arena_matches")}
    assert {
        "reward_hold_status",
        "reward_release_at",
        "appeal_deadline_at",
        "current_result_type",
        "result_version",
        "current_decision_id",
        "initial_decision_id",
    }.issubset(match_columns)
    appeal_columns = {item["name"] for item in inspector.get_columns("arena_appeals")}
    assert {"reason", "submitted_at", "deadline_at"}.issubset(appeal_columns)
    wallet_columns = {item["name"] for item in inspector.get_columns("wallets")}
    assert "locked_reward_efc" in wallet_columns
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT public_id, status, reward_hold_status, result_version "
            "FROM arena_matches WHERE id = 1"
        )).one()
        wallet_row = connection.execute(text(
            "SELECT efc_balance, locked_efc, locked_reward_efc "
            "FROM wallets WHERE telegram_id = 1001"
        )).one()
    assert tuple(row) == ("LEGACY-ACTIVE", "PLAYING", "NONE", 0)
    assert tuple(wallet_row) == (25, 500, 0)
