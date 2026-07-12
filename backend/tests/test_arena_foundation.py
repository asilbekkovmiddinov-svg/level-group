from datetime import datetime, timezone
from decimal import Decimal

from app.models.match import (
    LEGACY_MATCH_STATUS_MAPPING,
    Match,
    MatchGameType,
    MatchStatus,
    map_legacy_match_status,
)
from app.models.user import User
from app.schemas.match import MatchInternalResponse, MatchResponse


FIXED_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def build_match(*, creator_name="Ali", opponent_name=None):
    match = Match(
        id=42,
        creator_telegram_id=1001,
        opponent_telegram_id=2002 if opponent_name else None,
        game_type=MatchGameType.EFOOTBALL,
        efc_amount=Decimal("100"),
        total_pool=Decimal("200"),
        commission_amount=Decimal("10"),
        winner_reward=Decimal("190"),
        status=MatchStatus.WAITING_PLAYER,
        scheduled_at=FIXED_NOW,
        creator_ready=False,
        opponent_ready=False,
        creator_result_screenshot="creator-screenshot-file-id",
        opponent_result_screenshot="opponent-screenshot-file-id",
        creator_result_video="creator-video-file-id",
        opponent_result_video="opponent-video-file-id",
        room_code="private-room-code",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )
    match.creator = User(telegram_id=1001, username="ali", first_name=creator_name)
    if opponent_name:
        match.opponent = User(
            telegram_id=2002,
            username="vali",
            first_name=opponent_name,
        )
    return match


def test_legacy_status_mapping_and_target_aliases_are_explicit():
    assert LEGACY_MATCH_STATUS_MAPPING["SCHEDULED"] == "WAITING_READY"
    assert LEGACY_MATCH_STATUS_MAPPING["READY_CHECK"] == "WAITING_READY"
    assert LEGACY_MATCH_STATUS_MAPPING["WAITING_ROOM_CODE"] == "ROOM_READY"
    assert LEGACY_MATCH_STATUS_MAPPING["MATCH_STARTED"] == "PLAYING"
    assert LEGACY_MATCH_STATUS_MAPPING["TECHNICAL_WIN"] == "TECHNICAL_REVIEW"
    assert MatchStatus.SCHEDULED is MatchStatus.WAITING_READY
    assert MatchStatus.TECHNICAL_WIN is MatchStatus.TECHNICAL_REVIEW


def test_unknown_legacy_status_is_not_coerced():
    assert map_legacy_match_status("UNRECOGNIZED") is None
    assert map_legacy_match_status("ROOM_CREATED") is None


def test_new_match_defaults_to_efootball_and_new_foundation_columns_are_nullable():
    game_type_column = Match.__table__.c.game_type

    assert game_type_column.default.arg is MatchGameType.EFOOTBALL
    assert game_type_column.nullable is False
    for column_name in (
        "creator_rules_accepted_at",
        "opponent_rules_accepted_at",
        "ready_window_started_at",
        "ready_deadline_at",
        "creator_result_video",
        "opponent_result_video",
        "creator_result_video_uploaded_at",
        "opponent_result_video_uploaded_at",
    ):
        assert Match.__table__.c[column_name].nullable is True


def test_public_match_response_excludes_identity_room_and_evidence_secrets():
    response = MatchResponse.model_validate(build_match(creator_name="Ali", opponent_name="Vali"))
    payload = response.model_dump()

    assert payload["creator_display_name"] == "Ali"
    assert payload["opponent_display_name"] == "Vali"
    for sensitive_field in (
        "creator_telegram_id",
        "opponent_telegram_id",
        "creator_username",
        "opponent_username",
        "room_code",
        "creator_result_screenshot",
        "opponent_result_screenshot",
        "creator_result_video",
        "opponent_result_video",
        "admin_telegram_id",
    ):
        assert sensitive_field not in payload


def test_public_display_name_uses_safe_fallback():
    response = MatchResponse.model_validate(build_match(creator_name=None))

    assert response.creator_display_name == "O‘yinchi"
    assert response.opponent_display_name == "O‘yinchi"


def test_internal_response_retains_required_admin_metadata():
    response = MatchInternalResponse.model_validate(
        build_match(creator_name="Ali", opponent_name="Vali")
    )

    assert response.creator_telegram_id == 1001
    assert response.creator_username == "ali"
    assert response.room_code == "private-room-code"
    assert response.creator_result_screenshot == "creator-screenshot-file-id"
    assert response.creator_result_video == "creator-video-file-id"
    assert response.creator_evidence_complete is True
    assert response.opponent_evidence_complete is True
