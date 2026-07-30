from dataclasses import dataclass
from pathlib import Path

from app.services.arena_v3 import ArenaV3ServiceError


MAX_SCREENSHOT_SIZE = 5 * 1024 * 1024
MAX_APPEAL_VIDEO_SIZE = 50 * 1024 * 1024
SCREENSHOT_TYPES = {
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}
APPEAL_VIDEO_TYPES = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
}


@dataclass(frozen=True)
class ScreenshotMetadata:
    extension: str
    mime_type: str
    file_size: int
    width: int
    height: int


@dataclass(frozen=True)
class AppealVideoMetadata:
    extension: str
    mime_type: str
    file_size: int


def _png_dimensions(content: bytes) -> tuple[int, int]:
    if len(content) < 24 or content[12:16] != b"IHDR":
        raise ArenaV3ServiceError("Invalid PNG screenshot")
    return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(content):
        if content[index] != 0xFF:
            index += 1
            continue
        marker = content[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(content):
            break
        segment_length = int.from_bytes(content[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(content):
            break
        if marker in {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }:
            if segment_length < 7:
                break
            height = int.from_bytes(content[index + 3:index + 5], "big")
            width = int.from_bytes(content[index + 5:index + 7], "big")
            return width, height
        index += segment_length
    raise ArenaV3ServiceError("Invalid JPEG screenshot")


def validate_screenshot(filename: str | None, content_type: str | None, content: bytes):
    extension = Path(filename or "").suffix.lower().lstrip(".")
    if extension not in SCREENSHOT_TYPES or not content:
        raise ArenaV3ServiceError("Screenshot must be PNG or JPEG")
    if len(content) > MAX_SCREENSHOT_SIZE:
        error = ArenaV3ServiceError("Screenshot exceeds the 5 MB limit")
        error.status_code = 413
        raise error
    expected_type, signature = SCREENSHOT_TYPES[extension]
    if content_type != expected_type or not content.startswith(signature):
        raise ArenaV3ServiceError("Invalid screenshot file")
    width, height = (
        _png_dimensions(content)
        if extension == "png"
        else _jpeg_dimensions(content)
    )
    if width < 1 or height < 1:
        raise ArenaV3ServiceError("Invalid screenshot dimensions")
    return ScreenshotMetadata(
        extension="jpg" if extension == "jpeg" else extension,
        mime_type=expected_type,
        file_size=len(content),
        width=width,
        height=height,
    )


def validate_appeal_video(
    filename: str | None, content_type: str | None, content: bytes
) -> AppealVideoMetadata:
    extension = Path(filename or "").suffix.lower().lstrip(".")
    expected_type = APPEAL_VIDEO_TYPES.get(extension)
    if expected_type is None or not content:
        raise ArenaV3ServiceError("Appeal video must be MP4, MOV or WEBM")
    if len(content) > MAX_APPEAL_VIDEO_SIZE:
        error = ArenaV3ServiceError("Appeal video exceeds the 50 MB limit")
        error.status_code = 413
        raise error
    if content_type != expected_type:
        raise ArenaV3ServiceError("Appeal video content type is invalid")
    is_webm = extension == "webm" and content.startswith(b"\x1a\x45\xdf\xa3")
    is_iso_media = extension in {"mp4", "mov"} and (
        len(content) >= 12 and content[4:8] == b"ftyp"
    )
    if not (is_webm or is_iso_media):
        raise ArenaV3ServiceError("Appeal video signature is invalid")
    return AppealVideoMetadata(
        extension=extension,
        mime_type=expected_type,
        file_size=len(content),
    )
