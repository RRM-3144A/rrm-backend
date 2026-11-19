"""Realistic test data for development and the MVP demo.

Run after the migrations:

    alembic upgrade head
    python -m app.seed

Running it again does not duplicate anything: users, teams, categories and resources are
matched by their unique names/e-mails, and reservations, maintenance windows, trainings and
the waitlist are only added while those tables are empty. Reservations are placed in the
week after the current one, so the demo calendar always has data.

The e-mails in ADMIN_EMAILS (your own Google accounts) become administrators of every
resource, so you can sign in and approve the seeded requests.
"""

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    MaintenanceWindow,
    OperatingSchedule,
    Reservation,
    ReservationStatus,
    Resource,
    ResourceCategory,
    ResourceStatus,
    ResourceTraining,
    Role,
    Team,
    User,
    WaitlistEntry,
)
from app.services.schedule import local_timezone

DOMAIN = "student.usv.ro"

TEAMS = ["Echipa Robotică", "Echipa Bioinformatică", "Echipa IoT"]

# (first name, last name, e-mail prefix, role, team)
USERS = [
    ("Elena", "Munteanu", "elena.munteanu", Role.ADMIN, None),
    ("Radu", "Ciobanu", "radu.ciobanu", Role.ADMIN, None),
    ("Ioana", "Popescu", "ioana.popescu", Role.STUDENT, "Echipa Robotică"),
    ("Andrei", "Rusu", "andrei.rusu", Role.STUDENT, "Echipa Robotică"),
    ("Maria", "Lungu", "maria.lungu", Role.STUDENT, "Echipa Bioinformatică"),
    ("Vlad", "Grigore", "vlad.grigore", Role.STUDENT, "Echipa Bioinformatică"),
    ("Bianca", "Tănase", "bianca.tanase", Role.STUDENT, "Echipa IoT"),
    ("Cristian", "Moldovan", "cristian.moldovan", Role.STUDENT, "Echipa IoT"),
]

CATEGORIES = {
    "Imprimante 3D": "Imprimante FDM și cu rășină pentru prototipuri.",
    "Microscoape": "Microscoape optice și stereo pentru analiza probelor.",
    "Echipamente de laborator": "Osciloscoape, surse de alimentare și stații de lipit.",
    "Săli de lucru": "Săli pentru întâlniri de echipă și sesiuni de lucru.",
}

WEEKDAYS_8_TO_16 = [(d, time(8), time(16)) for d in range(5)]
WEEKDAYS_9_TO_17_WITH_BREAK = [(d, time(9), time(12)) for d in range(5)] + [
    (d, time(13), time(17)) for d in range(5)
]
EVERY_DAY_8_TO_20 = [(d, time(8), time(20)) for d in range(7)]

# name: fields, schedule, administrator e-mail prefixes
RESOURCES = {
    "Prusa MK4": (
        dict(
            category="Imprimante 3D",
            description="Imprimantă FDM, volum 25×21×22 cm, PLA/PETG.",
            location="Corp C, sala C203", floor=2, model="Prusa MK4",
            max_duration_min=240, requires_training=True,
        ),
        WEEKDAYS_8_TO_16,
        ["elena.munteanu"],
    ),
    "Formlabs Form 3": (
        dict(
            category="Imprimante 3D",
            description="Imprimantă SLA cu rășină pentru piese de precizie.",
            location="Corp C, sala C203", floor=2, model="Formlabs Form 3",
            max_duration_min=180, requires_training=True,
            status=ResourceStatus.MAINTENANCE,
        ),
        WEEKDAYS_8_TO_16,
        ["elena.munteanu"],
    ),
    "Microscop Zeiss Axio": (
        dict(
            category="Microscoape",
            description="Microscop optic cu cameră digitală.",
            location="Corp A, laborator A105", floor=1, model="Zeiss Axio Lab.A1",
            max_duration_min=120,
        ),
        WEEKDAYS_9_TO_17_WITH_BREAK,
        ["radu.ciobanu"],
    ),
    "Stereomicroscop Leica": (
        dict(
            category="Microscoape",
            location="Corp A, laborator A105", floor=1, model="Leica S9i",
            max_duration_min=120, status=ResourceStatus.INACTIVE,
        ),
        WEEKDAYS_9_TO_17_WITH_BREAK,
        ["radu.ciobanu"],
    ),
    "Osciloscop Rigol": (
        dict(
            category="Echipamente de laborator",
            description="Osciloscop digital, 4 canale, 100 MHz.",
            location="Corp C, sala C110", floor=1, model="Rigol DS1104Z",
            equipment="Sonde 10x, cabluri BNC", max_concurrent_teams=2,
        ),
        WEEKDAYS_8_TO_16,
        ["elena.munteanu", "radu.ciobanu"],
    ),
    "Stație de lipit Weller": (
        dict(
            category="Echipamente de laborator",
            location="Corp C, sala C110", floor=1, model="Weller WE1010",
            max_concurrent_teams=2, requires_training=True,
        ),
        WEEKDAYS_8_TO_16,
        ["elena.munteanu"],
    ),
    "Sala de proiect C305": (
        dict(
            category="Săli de lucru",
            description="Sală cu tablă interactivă și videoproiector.",
            location="Corp C, sala C305", floor=3, seats=12,
            equipment="Videoproiector, tablă interactivă", max_duration_min=180,
        ),
        EVERY_DAY_8_TO_20,
        ["radu.ciobanu"],
    ),
}


def _email(prefix: str) -> str:
    return f"{prefix}@{DOMAIN}"


def _get_or_create(db: Session, model, defaults: dict | None = None, **keys):
    instance = db.scalar(select(model).filter_by(**keys))
    if instance is None:
        instance = model(**keys, **(defaults or {}))
        db.add(instance)
    return instance


def _is_empty(db: Session, model) -> bool:
    return db.scalar(select(func.count()).select_from(model)) == 0


def next_monday(today: date) -> date:
    """The Monday of the week after `today`'s week."""
    return today + timedelta(days=7 - today.weekday())


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    """Local wall-clock time on `day`, returned in UTC (how the API stores times)."""
    return datetime.combine(day, time(hour, minute), tzinfo=local_timezone()).astimezone(
        timezone.utc
    )


def _seed_people(db: Session) -> dict[str, User]:
    teams = {name: _get_or_create(db, Team, name=name) for name in TEAMS}
    users = {}
    for first_name, last_name, prefix, role, team in USERS:
        users[prefix] = _get_or_create(
            db,
            User,
            email=_email(prefix),
            defaults=dict(
                first_name=first_name,
                last_name=last_name,
                role=role,
                team=teams[team] if team else None,
            ),
        )
    return users


def _real_admins(db: Session) -> list[User]:
    """Accounts from ADMIN_EMAILS, created ahead of their first Google sign-in."""
    admins = []
    for email in sorted(settings.admin_email_set):
        prefix = email.split("@")[0]
        user = _get_or_create(
            db,
            User,
            email=email,
            defaults=dict(first_name=prefix.split(".")[0].title(), last_name="Admin"),
        )
        user.role = Role.ADMIN
        admins.append(user)
    return admins


def _seed_resources(db: Session, users: dict[str, User]) -> dict[str, Resource]:
    categories = {
        name: _get_or_create(db, ResourceCategory, name=name, defaults={"description": text})
        for name, text in CATEGORIES.items()
    }
    real_admins = _real_admins(db)
    resources = {}
    for name, (fields, schedule, admin_prefixes) in RESOURCES.items():
        fields = dict(fields)
        category = categories[fields.pop("category")]
        resource = db.scalar(select(Resource).where(Resource.name == name))
        if resource is None:
            resource = Resource(name=name, category=category, **fields)
            resource.schedules = [
                OperatingSchedule(weekday=w, start_time=s, end_time=e) for w, s, e in schedule
            ]
            db.add(resource)
        for admin in [users[p] for p in admin_prefixes] + real_admins:
            if admin not in resource.admins:
                resource.admins.append(admin)
        resources[name] = resource
    return resources


def _seed_activity(
    db: Session, users: dict[str, User], resources: dict[str, Resource], monday: date
) -> None:
    ioana, andrei = users["ioana.popescu"], users["andrei.rusu"]
    maria, vlad = users["maria.lungu"], users["vlad.grigore"]
    bianca, cristian = users["bianca.tanase"], users["cristian.moldovan"]
    elena, radu = users["elena.munteanu"], users["radu.ciobanu"]
    prusa, form3 = resources["Prusa MK4"], resources["Formlabs Form 3"]
    zeiss, rigol = resources["Microscop Zeiss Axio"], resources["Osciloscop Rigol"]
    weller, room = resources["Stație de lipit Weller"], resources["Sala de proiect C305"]
    tuesday, wednesday, thursday = (monday + timedelta(days=n) for n in (1, 2, 3))
    last_friday = monday - timedelta(days=3)

    if _is_empty(db, ResourceTraining):
        db.add_all(
            ResourceTraining(user_id=u.id, resource_id=r.id)
            for u, r in [(ioana, prusa), (andrei, prusa), (bianca, weller)]
        )

    if _is_empty(db, Reservation):
        def reserve(user, resource, day, start, end, status, **extra):
            db.add(
                Reservation(
                    user=user, resource=resource, team=user.team,
                    start_at=_at(day, *start), end_at=_at(day, *end), status=status, **extra
                )
            )

        approved, pending = ReservationStatus.APPROVED, ReservationStatus.PENDING
        decided = {"decided_at": _at(monday - timedelta(days=4), 10)}
        reserve(ioana, prusa, monday, (9, 0), (12, 0), approved,
                purpose="Carcasă pentru senzorul de distanță", decided_by=elena.id, **decided)
        reserve(andrei, prusa, monday, (13, 0), (15, 0), pending,
                purpose="Suport pentru motoare")
        reserve(cristian, prusa, tuesday, (10, 0), (11, 30),
                ReservationStatus.AWAITING_TRAINING, purpose="Prima imprimare",
                decided_by=elena.id, **decided)
        reserve(maria, zeiss, monday, (9, 0), (11, 0), approved,
                purpose="Analiza culturilor celulare", decided_by=radu.id, **decided)
        reserve(vlad, zeiss, tuesday, (13, 30), (15, 0), pending, purpose="Probe de țesut")
        reserve(vlad, zeiss, wednesday, (9, 0), (10, 0), ReservationStatus.REJECTED,
                purpose="Probe de țesut", decided_by=radu.id,
                rejection_reason="Microscopul este rezervat pentru un curs în acest interval.",
                **decided)
        # The oscilloscope can be shared by two teams at the same time.
        reserve(bianca, rigol, monday, (10, 0), (12, 0), approved,
                purpose="Măsurători pe placa ESP32", decided_by=elena.id, **decided)
        reserve(ioana, rigol, monday, (10, 30), (11, 30), pending, purpose="Test driver motoare")
        reserve(bianca, weller, tuesday, (14, 0), (15, 0), approved,
                purpose="Lipire conectori", decided_by=elena.id, **decided)
        reserve(maria, room, thursday, (16, 0), (18, 0), approved,
                purpose="Întâlnire de echipă", decided_by=radu.id, **decided)
        reserve(andrei, room, wednesday, (12, 0), (13, 0), ReservationStatus.CANCELLED,
                purpose="Întâlnire anulată")
        reserve(ioana, room, last_friday, (14, 0), (16, 0), ReservationStatus.COMPLETED,
                purpose="Pregătire prezentare", decided_by=radu.id,
                decided_at=_at(last_friday - timedelta(days=2), 9))

    if _is_empty(db, MaintenanceWindow):
        db.add_all(
            [
                MaintenanceWindow(
                    resource_id=rigol.id, start_at=_at(wednesday, 8), end_at=_at(wednesday, 12),
                    reason="Calibrare anuală", created_by=elena.id,
                ),
                MaintenanceWindow(
                    resource_id=form3.id, start_at=_at(monday, 8),
                    end_at=_at(monday + timedelta(days=4), 16),
                    reason="Înlocuire rezervor de rășină", created_by=elena.id,
                ),
            ]
        )

    if _is_empty(db, WaitlistEntry):
        db.add(
            WaitlistEntry(
                user_id=andrei.id, resource=prusa, start_at=_at(monday, 9), end_at=_at(monday, 12)
            )
        )


def seed(db: Session, today: date | None = None) -> None:
    today = today or datetime.now(local_timezone()).date()
    users = _seed_people(db)
    resources = _seed_resources(db, users)
    db.flush()
    _seed_activity(db, users, resources, next_monday(today))
    db.commit()


def main() -> None:
    from app.database import SessionLocal

    with SessionLocal() as db:
        seed(db)
        counts = {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in (User, Team, ResourceCategory, Resource, Reservation, MaintenanceWindow)
        }
    print("Test data loaded:", ", ".join(f"{n} {t}" for t, n in counts.items()))


if __name__ == "__main__":
    main()
