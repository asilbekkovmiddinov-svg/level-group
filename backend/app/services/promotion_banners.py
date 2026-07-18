from pathlib import Path

from fastapi import HTTPException, UploadFile


MAX_PROMOTION_BANNER_SIZE = 5 * 1024 * 1024
BANNER_SIGNATURES = {
    "jpg": (b"\xff\xd8\xff", "image/jpeg"),
    "jpeg": (b"\xff\xd8\xff", "image/jpeg"),
    "png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    "webp": (b"RIFF", "image/webp"),
}


def validate_promotion_banner(upload: UploadFile, content: bytes) -> tuple[str, str]:
    extension = Path(upload.filename or "").suffix.lower().lstrip(".")
    if extension not in BANNER_SIGNATURES or not content:
        raise HTTPException(400, "Banner must be JPG, PNG or WEBP")
    if len(content) > MAX_PROMOTION_BANNER_SIZE:
        raise HTTPException(413, "Banner exceeds the 5 MB limit")
    signature, content_type = BANNER_SIGNATURES[extension]
    valid_signature = content.startswith(signature)
    if extension == "webp":
        valid_signature = valid_signature and content[8:12] == b"WEBP"
    if not valid_signature or upload.content_type != content_type:
        raise HTTPException(400, "Invalid banner image")
    normalized_extension = "jpg" if extension == "jpeg" else extension
    return normalized_extension, content_type
