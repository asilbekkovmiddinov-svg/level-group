from sqlalchemy.orm import Session

from app.repositories.arena_v3 import ArenaV3Repository


class ArenaV3FoundationOnly(NotImplementedError):
    """Raised for business operations intentionally deferred beyond Sprint 3."""


class ArenaV3Service:
    def __init__(self, db: Session):
        self.db = db
        self.repository = ArenaV3Repository(db)

    def create_match(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 create business logic is not enabled")

    def join_match(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 join business logic is not enabled")

    def ready(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 ready business logic is not enabled")

    def submit_room_code(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 room-code business logic is not enabled")

    def upload_screenshot(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 screenshot business logic is not enabled")

    def start_ai_review(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 AI integration is not enabled")

    def submit_appeal(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 appeal business logic is not enabled")

    def finish_match(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 settlement business logic is not enabled")

    def cancel_match(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 cancel business logic is not enabled")
