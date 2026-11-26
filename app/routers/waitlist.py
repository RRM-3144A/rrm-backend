from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, WaitlistEntry
from app.schemas import WaitlistCreate, WaitlistEntryOut
from app.services.waitlist import join_waitlist, leave_waitlist, list_my_waitlist

router = APIRouter(prefix="/waitlist", tags=["Waitlist"])


@router.post("", response_model=WaitlistEntryOut, status_code=status.HTTP_201_CREATED)
def join_waitlist_endpoint(
    body: WaitlistCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WaitlistEntry:
    return join_waitlist(db, user, body)


@router.get("", response_model=list[WaitlistEntryOut])
def list_my_waitlist_endpoint(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WaitlistEntry]:
    return list_my_waitlist(db, user)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def leave_waitlist_endpoint(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    leave_waitlist(db, entry_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)