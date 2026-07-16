from pydantic import BaseModel, ConfigDict, field_validator


class CoinOrderMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 1000:
            raise ValueError("Message must contain 1-1000 characters")
        return value


class OperatorMessageCreate(CoinOrderMessageCreate):
    admin_id: int


class OperatorChatAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_id: int
    action: str
