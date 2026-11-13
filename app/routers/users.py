from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models import Role, Team, User
from app.schemas import TeamCreate, TeamOut, UserOut, UserUpdate

router = APIRouter(tags=["Users"])


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.last_name, User.first_name)))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    changes = body.model_dump(exclude_unset=True)
    if "role" in changes:
        if user.id == admin.id and changes["role"] != Role.ADMIN:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove your own admin role")
        user.role = changes["role"]
    if "team_id" in changes:
        if changes["team_id"] is not None and db.get(Team, changes["team_id"]) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Team not found")
        user.team_id = changes["team_id"]

    db.commit()
    db.refresh(user)
    return user


@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db)) -> list[Team]:
    return list(db.scalars(select(Team).order_by(Team.name)))


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(
    body: TeamCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> Team:
    team = Team(name=body.name.strip())
    db.add(team)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A team with this name already exists") from exc
    db.refresh(team)
    return team
