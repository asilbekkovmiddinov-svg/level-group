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


class CredentialOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_id: int
    session_id: str | None = None


class CoinOrderDetailsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    konami_login: str
    konami_password: str

    @field_validator("konami_login")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 254 or "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Invalid MyKonami email")
        return value

    @field_validator("konami_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 4 or len(value) > 256:
            raise ValueError("Invalid MyKonami password")
        return value
