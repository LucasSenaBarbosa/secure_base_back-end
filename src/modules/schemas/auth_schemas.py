from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Role(StrEnum):
    MASTER = "master"
    PRIMARY = "primary"
    MEMBER = "member"


class AuthenticatedUser(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    role: Role


class UserProfile(AuthenticatedUser):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class RegisterResponse(BaseModel):
    message: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile
    csrf_token: str


class RefreshResponse(LoginResponse):
    pass


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
