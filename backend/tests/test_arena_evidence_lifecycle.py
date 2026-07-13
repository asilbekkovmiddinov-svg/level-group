from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.crud import match as match_crud
from app.models.match import MatchStatus
from app.schemas.match import MatchScreenshotUpload
from app.services.arena_state_machine import ArenaTransitionError


class FakeMatch(SimpleNamespace):
    @property
    def creator_evidence_complete(self):
        return bool(self.creator_result_screenshot and self.creator_result_video)

    @property
    def opponent_evidence_complete(self):
        return bool(self.opponent_result_screenshot and self.opponent_result_video)


def make_match(status=MatchStatus.PLAYING, **overrides):
    values = {
        "id": 42,
        "status": status,
        "creator_telegram_id": 1001,
        "opponent_telegram_id": 2002,
        "creator_result_screenshot": None,
        "creator_result_uploaded_at": None,
        "creator_result_video": None,
        "creator_result_video_uploaded_at": None,
        "opponent_result_screenshot": None,
        "opponent_result_uploaded_at": None,
        "opponent_result_video": None,
        "opponent_result_video_uploaded_at": None,
        "updated_at": None,
    }
    values.update(overrides)
    return FakeMatch(**values)


class FakeSession:
    def __init__(self):
        self.commit_count = 0
        self.refresh_count = 0

    def commit(self):
        self.commit_count += 1

    def refresh(self, _match):
        self.refresh_count += 1


def upload(monkeypatch, match, telegram_id, screenshot=None, video=None):
    db = FakeSession()
    lock_calls = []

    def locked_match(_db, match_id):
        lock_calls.append(match_id)
        return match

    monkeypatch.setattr(match_crud, "get_match_for_update", locked_match)
    result = match_crud.upload_result_screenshot(
        db,
        match.id,
        telegram_id,
        screenshot_file_id=screenshot,
        video_file_id=video,
    )
    return result, db, lock_calls


def test_existing_screenshot_contract_remains_valid_and_video_is_additive():
    screenshot = MatchScreenshotUpload.model_validate({"screenshot_file_id": "photo-id"})
    video = MatchScreenshotUpload.model_validate({"video_file_id": "video-id"})

    assert screenshot.screenshot_file_id == "photo-id"
    assert video.video_file_id == "video-id"
    with pytest.raises(ValidationError):
        MatchScreenshotUpload.model_validate({})


def test_creator_and_opponent_evidence_succeed_and_stay_playing(monkeypatch):
    match = make_match()

    creator, creator_db, creator_locks = upload(
        monkeypatch, match, 1001, screenshot="creator-photo", video="creator-video"
    )
    assert creator.creator_evidence_complete is True
    assert creator.status == MatchStatus.PLAYING
    assert creator_locks == [42]
    assert creator_db.commit_count == 1

    opponent, opponent_db, _ = upload(
        monkeypatch, match, 2002, screenshot="opponent-photo"
    )
    assert opponent.opponent_result_screenshot == "opponent-photo"
    assert opponent.opponent_evidence_complete is False
    assert opponent.status == MatchStatus.PLAYING
    assert opponent_db.commit_count == 1


def test_all_required_evidence_moves_match_to_waiting_admin(monkeypatch):
    match = make_match(
        creator_result_screenshot="creator-photo",
        creator_result_video="creator-video",
        opponent_result_screenshot="opponent-photo",
    )

    result, db, _ = upload(monkeypatch, match, 2002, video="opponent-video")

    assert result.creator_evidence_complete is True
    assert result.opponent_evidence_complete is True
    assert result.status == MatchStatus.WAITING_ADMIN
    assert db.commit_count == 1


@pytest.mark.parametrize(
    ("telegram_id", "screenshot", "video"),
    [
        (1001, "new-photo", None),
        (1001, None, "new-video"),
        (2002, "new-photo", None),
        (2002, None, "new-video"),
    ],
)
def test_duplicate_evidence_slot_is_rejected(
    monkeypatch, telegram_id, screenshot, video
):
    match = make_match(
        creator_result_screenshot="creator-photo",
        creator_result_video="creator-video",
        opponent_result_screenshot="opponent-photo",
        opponent_result_video="opponent-video",
    )
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    with pytest.raises(ArenaTransitionError):
        match_crud.upload_result_screenshot(
            db,
            42,
            telegram_id,
            screenshot_file_id=screenshot,
            video_file_id=video,
        )
    assert db.commit_count == 0


def test_outsider_cannot_submit_evidence(monkeypatch):
    match = make_match()
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    with pytest.raises(ValueError, match="ishtirokchisi emassiz"):
        match_crud.upload_result_screenshot(db, 42, 9999, "outsider-photo")
    assert db.commit_count == 0


@pytest.mark.parametrize(
    "status",
    [
        MatchStatus.WAITING_PLAYER,
        MatchStatus.WAITING_READY,
        MatchStatus.ROOM_READY,
        MatchStatus.TECHNICAL_REVIEW,
        MatchStatus.WAITING_ADMIN,
        MatchStatus.COMPLETED,
        MatchStatus.CANCELLED,
    ],
)
def test_evidence_is_rejected_outside_playing(monkeypatch, status):
    match = make_match(status=status)
    db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: match)

    with pytest.raises(ArenaTransitionError):
        match_crud.upload_result_screenshot(db, 42, 1001, "photo")
    assert db.commit_count == 0


def test_parallel_slots_are_serialized_without_overwrite(monkeypatch):
    shared_match = make_match()

    first, first_db, _ = upload(monkeypatch, shared_match, 1001, screenshot="photo")
    assert first.creator_result_screenshot == "photo"
    assert first_db.commit_count == 1

    second, second_db, _ = upload(monkeypatch, shared_match, 1001, video="video")
    assert second.creator_result_screenshot == "photo"
    assert second.creator_result_video == "video"
    assert second_db.commit_count == 1

    third_db = FakeSession()
    monkeypatch.setattr(match_crud, "get_match_for_update", lambda *_: shared_match)
    with pytest.raises(ArenaTransitionError):
        match_crud.upload_result_screenshot(third_db, 42, 1001, "replacement")
    assert shared_match.creator_result_screenshot == "photo"
    assert third_db.commit_count == 0
