from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.core.arena_internal_auth import require_arena_internal_api_key
from app.core.database import get_db
from app.repositories.arena_v3 import ArenaV3Repository
from app.schemas.arena_v3 import ArenaV3MatchResponse
from app.services.arena_finished_result_edit import revise_finished_ticket_result
from app.services.arena_v3 import ArenaV3ServiceError
from fastapi import HTTPException


router = APIRouter(prefix="/internal/arena", tags=["Arena Finished Result Edit"])


class ArenaFinishedResultEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_id: int = Field(gt=0)
    owner_score: int = Field(ge=0, le=99)
    opponent_score: int = Field(ge=0, le=99)
    reason: str = Field(default="ADMIN_FINISHED_RESULT_CORRECTION", min_length=1, max_length=500)

    @model_validator(mode="after")
    def reject_draw(self):
        if self.owner_score == self.opponent_score:
            raise ValueError("Equal scores are not allowed; penalty shootout is mandatory")
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("Correction reason is required")
        return self


@router.post(
    "/matches/{match_id}/correct-result",
    response_model=ArenaV3MatchResponse,
)
def correct_finished_result(
    match_id: int,
    payload: ArenaFinishedResultEditRequest,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    try:
        return revise_finished_ticket_result(
            db,
            repository=ArenaV3Repository(db),
            match_id=match_id,
            admin_id=payload.admin_id,
            owner_score=payload.owner_score,
            opponent_score=payload.opponent_score,
            reason=payload.reason,
        )
    except ArenaV3ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
