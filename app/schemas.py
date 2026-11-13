from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models import ResourceStatus, Role


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


class CategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class CategoryOut(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_count: int = 0


class AdminSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    email: str


class ResourceFields(BaseModel):
    description: str | None = None
    status: ResourceStatus = ResourceStatus.ACTIVE
    max_concurrent_teams: int = Field(default=1, ge=1, le=2)
    location: str | None = Field(default=None, max_length=200)
    floor: int | None = None
    seats: int | None = Field(default=None, ge=0)
    equipment: str | None = None
    model: str | None = Field(default=None, max_length=200)
    max_duration_min: int | None = Field(default=None, gt=0, multiple_of=30)
    requires_training: bool = False


class ResourceCreate(ResourceFields):
    name: str = Field(min_length=1, max_length=200)
    category_id: int
    admin_ids: list[int] = []


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    description: str | None = None
    status: ResourceStatus | None = None
    max_concurrent_teams: int | None = Field(default=None, ge=1, le=2)
    location: str | None = Field(default=None, max_length=200)
    floor: int | None = None
    seats: int | None = Field(default=None, ge=0)
    equipment: str | None = None
    model: str | None = Field(default=None, max_length=200)
    max_duration_min: int | None = Field(default=None, gt=0, multiple_of=30)
    requires_training: bool | None = None
    admin_ids: list[int] | None = None


class ResourceOut(ResourceFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: CategoryBase
    category_id: int
    admins: list[AdminSummary]


class ScheduleInterval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weekday: int = Field(ge=0, le=6, description="0 = Monday, 6 = Sunday")
    start_time: time
    end_time: time


class ScheduleUpdate(BaseModel):
    intervals: list[ScheduleInterval]
