"""Add server-authoritative Penalty Duel matches."""

from alembic import op
import sqlalchemy as sa


revision = "20260817_penalty_duel"
down_revision = "20260814_adsgram_purpose"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "penalty_duel_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("player_one_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("player_two_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("player_one_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("player_two_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winner_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id")),
        sa.Column("reward_granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("round_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(64)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("player_one_id <> player_two_id", name="ck_penalty_duel_distinct_players"),
        sa.CheckConstraint("round_number > 0", name="ck_penalty_duel_round_positive"),
        sa.CheckConstraint("player_one_score >= 0", name="ck_penalty_duel_p1_score"),
        sa.CheckConstraint("player_two_score >= 0", name="ck_penalty_duel_p2_score"),
    )
    op.create_index(
        "ix_penalty_duel_matchmaking",
        "penalty_duel_matches",
        ["mode", "status", "created_at"],
    )
    for column in ("mode", "status", "player_one_id", "player_two_id", "winner_id"):
        op.create_index(
            f"ix_penalty_duel_matches_{column}",
            "penalty_duel_matches",
            [column],
        )

    op.create_table(
        "penalty_duel_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("penalty_duel_matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), sa.ForeignKey("users.telegram_id"), nullable=False),
        sa.Column("kick_direction", sa.String(16), nullable=False),
        sa.Column("keeper_direction", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("round_number > 0", name="ck_penalty_duel_submission_round"),
        sa.UniqueConstraint(
            "match_id",
            "round_number",
            "player_id",
            name="uq_penalty_duel_round_player",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_penalty_duel_submission_key"),
    )
    op.create_index("ix_penalty_duel_submissions_match_id", "penalty_duel_submissions", ["match_id"])
    op.create_index("ix_penalty_duel_submissions_player_id", "penalty_duel_submissions", ["player_id"])

    op.create_table(
        "penalty_duel_rounds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("penalty_duel_matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("player_one_kick", sa.String(16), nullable=False),
        sa.Column("player_one_keeper", sa.String(16), nullable=False),
        sa.Column("player_two_kick", sa.String(16), nullable=False),
        sa.Column("player_two_keeper", sa.String(16), nullable=False),
        sa.Column("player_one_goal", sa.Boolean(), nullable=False),
        sa.Column("player_two_goal", sa.Boolean(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("round_number > 0", name="ck_penalty_duel_result_round"),
        sa.UniqueConstraint("match_id", "round_number", name="uq_penalty_duel_round"),
    )
    op.create_index("ix_penalty_duel_rounds_match_id", "penalty_duel_rounds", ["match_id"])
    op.create_index(
        "ix_penalty_duel_round_match",
        "penalty_duel_rounds",
        ["match_id", "round_number"],
    )


def downgrade():
    op.drop_table("penalty_duel_rounds")
    op.drop_table("penalty_duel_submissions")
    op.drop_table("penalty_duel_matches")
