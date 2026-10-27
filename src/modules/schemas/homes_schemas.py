from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.schemas.auth_schemas import Role


class CreateHomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class HomeProfile(BaseModel):
    id: UUID
    name: str
    primary_user_id: UUID
    role: Role


class TransferHomePrimaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
