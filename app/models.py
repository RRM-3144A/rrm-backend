import enum
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, enum.Enum):
    STUDENT = "STUDENT"
    ADMIN = "ADMIN"


class ResourceStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    INACTIVE = "INACTIVE"


class ReservationStatus(str, enum.Enum):
    PENDING = "PENDING"
    AWAITING_TRAINING = "AWAITING_TRAINING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class NotificationType(str, enum.Enum):
    NEW_REQUEST = "NEW_REQUEST"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TRAINING_REQUIRED = "TRAINING_REQUIRED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SLOT_FREED = "SLOT_FREED"


def _enum(enum_class: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_class, name=name, values_callable=lambda e: [m.value for m in e])


resource_admins = Table(
    "resource_admins",
    Base.metadata,
    Column("resource_id", ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)

    members: Mapped[list["User"]] = relationship(back_populates="team")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    last_name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), default=Role.STUDENT)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    team: Mapped[Team | None] = relationship(back_populates="members")
    administered_resources: Mapped[list["Resource"]] = relationship(
        secondary=resource_admins, back_populates="admins"
    )


class ResourceCategory(Base):
    __tablename__ = "resource_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    resources: Mapped[list["Resource"]] = relationship(back_populates="category")


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("max_concurrent_teams BETWEEN 1 AND 2", name="ck_resources_max_teams"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int] = mapped_column(ForeignKey("resource_categories.id", ondelete="RESTRICT"))
    status: Mapped[ResourceStatus] = mapped_column(
        _enum(ResourceStatus, "resource_status"), default=ResourceStatus.ACTIVE
    )
    max_concurrent_teams: Mapped[int] = mapped_column(SmallInteger, default=1)
    location: Mapped[str | None] = mapped_column(String(200))
    floor: Mapped[int | None] = mapped_column(SmallInteger)
    seats: Mapped[int | None] = mapped_column(Integer)
    equipment: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(200))
    max_duration_min: Mapped[int | None] = mapped_column(Integer)
    requires_training: Mapped[bool] = mapped_column(Boolean, default=False)

    category: Mapped[ResourceCategory] = relationship(back_populates="resources")
    admins: Mapped[list[User]] = relationship(
        secondary=resource_admins, back_populates="administered_resources"
    )
    schedules: Mapped[list["OperatingSchedule"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )


class ResourceTraining(Base):
    __tablename__ = "resource_trainings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperatingSchedule(Base):
    __tablename__ = "operating_schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_schedules_weekday"),
        CheckConstraint("start_time < end_time", name="ck_schedules_interval"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    resource: Mapped[Resource] = relationship(back_populates="schedules")


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"
    __table_args__ = (CheckConstraint("start_at < end_at", name="ck_maintenance_interval"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (CheckConstraint("start_at < end_at", name="ck_reservations_interval"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReservationStatus] = mapped_column(
        _enum(ReservationStatus, "reservation_status"), default=ReservationStatus.PENDING
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    resource: Mapped[Resource] = relationship()
    team: Mapped[Team | None] = relationship()


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"
    __table_args__ = (
        CheckConstraint("start_at < end_at", name="ck_waitlist_interval"),
        UniqueConstraint("user_id", "resource_id", "start_at", "end_at", name="uq_waitlist_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resource: Mapped[Resource] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservations.id", ondelete="SET NULL")
    )
    type: Mapped[NotificationType] = mapped_column(_enum(NotificationType, "notification_type"))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
