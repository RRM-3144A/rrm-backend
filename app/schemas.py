import enum
from datetime import datetime, time

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

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


class SlotStatus(str, enum.Enum):
    FREE = "FREE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    MAINTENANCE = "MAINTENANCE"


class AvailabilitySlot(BaseModel):
    start_at: datetime
    end_at: datetime
    status: SlotStatus
    free_places: int = Field(description="Teams that can still book this slot")


class MaintenanceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    start_at: AwareDatetime
    end_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _end_after_start(self) -> "MaintenanceCreate":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class MaintenanceOut(BaseModel):
    id: int
    resource_id: int
    start_at: datetime
    end_at: datetime
    reason: str
    created_by: int | None
    cancelled_at: datetime | None

from app.models import ReservationStatus


class ReservationResourceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str | None = None
    requires_training: bool = False
    max_concurrent_teams: int = 1


class PendingReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    resource_id: int
    team_id: int | None = None
    start_at: datetime
    end_at: datetime
    purpose: str | None = None
    status: ReservationStatus
    needs_review: bool = False
    created_at: datetime | None = None
    user: UserOut
    resource: ReservationResourceSummary
    team: TeamOut | None = None
    is_first_reservation: bool
    has_completed_training: bool = False