from pydantic import BaseModel, ConfigDict, EmailStr


class AddHomeMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
