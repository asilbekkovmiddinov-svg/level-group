"""Add Arena V5 matchmaking, relay and lightweight evidence persistence."""

from alembic import op
import sqlalchemy as sa


revision = "20260826_arena_v5"
down_revision = "20260817_penalty_duel"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table_name):
    inspector = _inspector()
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name):
    inspector = _inspector()
    if not inspector.has_table(table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    if "efootball_username" not in _columns("users"):
        op.add_column(
            "users", sa.Column("efootball_username", sa.String(64), nullable=True)
        )
    if "flow_version" not in _columns("arena_matches"):
        op.add_column(
            "arena_matches",
            sa.Column(
                "flow_version", sa.Integer(), nullable=False, server_default="4"
            ),
        )
    if "bot_relay_token" not in _columns("arena_matches"):
        op.add_column(
            "arena_matches",
            sa.Column("bot_relay_token", sa.String(64), nullable=True),
        )
    if "ix_arena_matches_flow_version" not in _indexes("arena_matches"):
        op.create_index(
            "ix_arena_matches_flow_version", "arena_matches", ["flow_version"]
        )
    if "uq_arena_matches_bot_relay_token" not in _indexes("arena_matches"):
        op.create_index(
            "uq_arena_matches_bot_relay_token",
            "arena_matches",
            ["bot_relay_token"],
            unique=True,
        )
    if "points" not in _columns("arena_stats_v3"):
        op.add_column(
            "arena_stats_v3",
            sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        )
    op.execute(
        "UPDATE arena_stats_v3 SET points = wins * 3 + draws "
        "WHERE points = 0 AND (wins > 0 OR draws > 0)"
    )

    if not _inspector().has_table("arena_matchmaking_queue"):
        op.create_table(
            "arena_matchmaking_queue",
            sa.Column("player_id", sa.BigInteger(), nullable=False),
            sa.Column("efootball_username", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["player_id"], ["users.telegram_id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("player_id"),
        )
    if "ix_arena_matchmaking_queue_created" not in _indexes(
        "arena_matchmaking_queue"
    ):
        op.create_index(
            "ix_arena_matchmaking_queue_created",
            "arena_matchmaking_queue",
            ["created_at", "player_id"],
        )

    if not _inspector().has_table("arena_v5_screenshot_submissions"):
        op.create_table(
            "arena_v5_screenshot_submissions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("player_id", sa.BigInteger(), nullable=False),
            sa.Column("telegram_file_id", sa.String(500), nullable=False),
            sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
            sa.Column("admin_channel_message_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "delivery_status",
                sa.String(16),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column("last_error", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["match_id"], ["arena_matches.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["player_id"], ["users.telegram_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "match_id", "player_id", name="uq_arena_v5_submission_player"
            ),
        )
    submission_indexes = _indexes("arena_v5_screenshot_submissions")
    for name, columns in (
        ("ix_arena_v5_screenshot_submissions_match_id", ["match_id"]),
        ("ix_arena_v5_screenshot_submissions_player_id", ["player_id"]),
        ("ix_arena_v5_submission_status", ["delivery_status", "created_at"]),
    ):
        if name not in submission_indexes:
            op.create_index(name, "arena_v5_screenshot_submissions", columns)


def downgrade():
    inspector = _inspector()
    if inspector.has_table("arena_v5_screenshot_submissions"):
        op.drop_table("arena_v5_screenshot_submissions")
    if _inspector().has_table("arena_matchmaking_queue"):
        op.drop_table("arena_matchmaking_queue")
    if "points" in _columns("arena_stats_v3"):
        op.drop_column("arena_stats_v3", "points")
    match_indexes = _indexes("arena_matches")
    if "uq_arena_matches_bot_relay_token" in match_indexes:
        op.drop_index(
            "uq_arena_matches_bot_relay_token", table_name="arena_matches"
        )
    if "ix_arena_matches_flow_version" in match_indexes:
        op.drop_index(
            "ix_arena_matches_flow_version", table_name="arena_matches"
        )
    if "bot_relay_token" in _columns("arena_matches"):
        op.drop_column("arena_matches", "bot_relay_token")
    if "flow_version" in _columns("arena_matches"):
        op.drop_column("arena_matches", "flow_version")
    if "efootball_username" in _columns("users"):
        op.drop_column("users", "efootball_username")
