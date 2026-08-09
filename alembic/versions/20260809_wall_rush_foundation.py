"""Add Wall Rush match and ticket persistence."""

from alembic import op
import sqlalchemy as sa


revision = "20260809_wall_rush"
down_revision = "20260808_coin_packages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wall_rush_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("red_player_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("blue_player_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("current_turn_player_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("red_row", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("red_column", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("blue_row", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("blue_column", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("red_walls_remaining", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("blue_walls_remaining", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("walls", sa.JSON(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("turn_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("winner_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("cancel_reason", sa.String(255)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("red_player_id <> blue_player_id", name="ck_wall_rush_distinct_players"),
        sa.CheckConstraint("red_walls_remaining BETWEEN 0 AND 10", name="ck_wall_rush_red_walls"),
        sa.CheckConstraint("blue_walls_remaining BETWEEN 0 AND 10", name="ck_wall_rush_blue_walls"),
        sa.CheckConstraint("turn_number > 0", name="ck_wall_rush_turn_number"),
    )
    op.create_index("ix_wall_rush_matchmaking", "wall_rush_matches", ["mode", "status", "created_at"])
    for column in ("mode", "status", "red_player_id", "blue_player_id", "winner_id"):
        op.create_index(f"ix_wall_rush_matches_{column}", "wall_rush_matches", [column])

    op.create_table(
        "wall_rush_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("wall_rush_matches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("match_id", "sequence", name="uq_wall_rush_action_sequence"),
        sa.UniqueConstraint("match_id", "idempotency_key", name="uq_wall_rush_action_idempotency"),
    )
    op.create_index("ix_wall_rush_actions_match_id", "wall_rush_actions", ["match_id"])
    op.create_index("ix_wall_rush_actions_player_id", "wall_rush_actions", ["player_id"])

    op.create_table(
        "game_ticket_wallets",
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), primary_key=True),
        sa.Column("game_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_game_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tournament_tickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_rewarded_ad_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("game_tickets >= 0", name="ck_game_ticket_wallet_game"),
        sa.CheckConstraint("locked_game_tickets >= 0", name="ck_game_ticket_wallet_locked"),
        sa.CheckConstraint("tournament_tickets >= 0", name="ck_game_ticket_wallet_tournament"),
    )

    op.create_table(
        "game_ticket_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("ticket_kind", sa.String(16), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("wall_rush_matches.id", ondelete="SET NULL")),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount <> 0", name="ck_game_ticket_ledger_nonzero"),
        sa.UniqueConstraint("idempotency_key", name="uq_game_ticket_ledger_idempotency"),
    )
    op.create_index("ix_game_ticket_ledger_user_created", "game_ticket_ledger", ["telegram_id", "created_at"])
    op.create_index("ix_game_ticket_ledger_telegram_id", "game_ticket_ledger", ["telegram_id"])


def downgrade():
    op.drop_table("game_ticket_ledger")
    op.drop_table("game_ticket_wallets")
    op.drop_table("wall_rush_actions")
    op.drop_table("wall_rush_matches")
