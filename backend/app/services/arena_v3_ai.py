from __future__ import annotations

import base64
import io
import re
import unicodedata
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.core import config


class ArenaV3AnalysisError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ScreenshotOCRResult(BaseModel):
    is_match_history: bool
    player_1_username: str = Field(min_length=1, max_length=64)
    player_2_username: str = Field(min_length=1, max_length=64)
    player_1_goals: int = Field(ge=0, le=99)
    player_2_goals: int = Field(ge=0, le=99)
    match_result: str = Field(max_length=64)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=255)


@dataclass(frozen=True)
class NormalizedResult:
    owner_score: int
    opponent_score: int
    confidence: float
    raw: dict


def validate_image(content: bytes) -> str:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            image_format = image.format
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ArenaV3AnalysisError("INVALID_IMAGE", "Screenshot is corrupted or unreadable") from error
    if image_format not in {"JPEG", "PNG", "WEBP"}:
        raise ArenaV3AnalysisError("INVALID_IMAGE_FORMAT", "Screenshot format is not supported")
    return image_format


def normalize_username(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def normalize_ocr_result(
    result: ScreenshotOCRResult,
    *,
    owner_username: str,
    opponent_username: str,
) -> NormalizedResult:
    if not result.is_match_history:
        raise ArenaV3AnalysisError("NOT_MATCH_HISTORY", "Screenshot is not an eFootball Match History result")
    player_1 = normalize_username(result.player_1_username)
    player_2 = normalize_username(result.player_2_username)
    owner = normalize_username(owner_username)
    opponent = normalize_username(opponent_username)
    if not owner or not opponent:
        raise ArenaV3AnalysisError("PROFILE_USERNAME_MISSING", "Arena profile username is missing")
    if player_1 == owner and player_2 == opponent:
        scores = result.player_1_goals, result.player_2_goals
    elif player_1 == opponent and player_2 == owner:
        scores = result.player_2_goals, result.player_1_goals
    else:
        raise ArenaV3AnalysisError("USERNAME_MISMATCH", "Screenshot usernames do not match Arena players")
    return NormalizedResult(
        owner_score=scores[0],
        opponent_score=scores[1],
        confidence=result.confidence,
        raw=result.model_dump(),
    )


class OpenAIVisionOCR:
    def __init__(self, client=None):
        if client is None:
            if not config.OPENAI_API_KEY:
                raise ArenaV3AnalysisError("AI_NOT_CONFIGURED", "AI provider is not configured")
            from openai import OpenAI
            client = OpenAI(
                api_key=config.OPENAI_API_KEY,
                timeout=config.ARENA_V3_AI_TIMEOUT_SECONDS,
            )
        self.client = client

    def analyze(self, content: bytes, mime_type: str) -> tuple[ScreenshotOCRResult, str | None]:
        validate_image(content)
        encoded = base64.b64encode(content).decode("ascii")
        try:
            response = self.client.responses.parse(
                model=config.ARENA_V3_AI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": [{
                            "type": "input_text",
                            "text": (
                                "Extract only visible eFootball Match History data. "
                                "Never infer hidden usernames or scores. Mark is_match_history false "
                                "unless the screen clearly shows a completed Match History result."
                            ),
                        }],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Analyze this screenshot."},
                            {
                                "type": "input_image",
                                "image_url": f"data:{mime_type};base64,{encoded}",
                                "detail": "high",
                            },
                        ],
                    },
                ],
                text_format=ScreenshotOCRResult,
            )
        except Exception as error:
            raise ArenaV3AnalysisError("OCR_PROVIDER_FAILED", "OCR provider request failed") from error
        if response.output_parsed is None:
            raise ArenaV3AnalysisError("OCR_EMPTY_RESULT", "OCR provider returned no structured result")
        return response.output_parsed, getattr(response, "id", None)


def winner_for_scores(match, owner_score: int, opponent_score: int) -> tuple[int | None, str]:
    if owner_score > opponent_score:
        return match.owner_id, "OWNER_WIN"
    if opponent_score > owner_score:
        return match.opponent_id, "OPPONENT_WIN"
    return None, "DRAW"
