from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import Role


class GoogleLoginRequest(BaseModel):
    id_token: str


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str
    last_name: str
    role: Role
    team: TeamOut | None = None
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class UserUpdate(BaseModel):
    role: Role | None = None
    team_id: int | None = None
