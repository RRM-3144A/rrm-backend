from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import ensure_resource_admin, get_current_user
from app.models import MaintenanceWindow, User
from app.routers.resources import get_resource_or_404
from app.schemas import MaintenanceCreate, MaintenanceOut
from app.services.maintenance import (
    MaintenanceConflict,
    cancel_window,
    create_window,
    list_windows,
    to_out,
)

router = APIRouter(prefix="/resources/{resource_id}/maintenance", tags=["Maintenance"])


@router.get("", response_model=list[MaintenanceOut])
def read_maintenance(
    resource_id: int,
    include_cancelled: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MaintenanceOut]:
    resource = get_resource_or_404(db, resource_id)
    return [to_out(w) for w in list_windows(db, resource, include_cancelled)]


@router.post("", response_model=MaintenanceOut, status_code=status.HTTP_201_CREATED)
def add_maintenance(
    resource_id: int,
    body: MaintenanceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MaintenanceOut:
    resource = get_resource_or_404(db, resource_id)
    ensure_resource_admin(resource, user)
    try:
        window = create_window(db, resource, user, body)
    except MaintenanceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    db.refresh(window)
    return to_out(window)


@router.delete("/{maintenance_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_maintenance(
    resource_id: int,
    maintenance_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Cancels the window instead of deleting it, so the history is kept."""
    resource = get_resource_or_404(db, resource_id)
    ensure_resource_admin(resource, user)
    window = db.get(MaintenanceWindow, maintenance_id)
    if window is None or window.resource_id != resource.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Maintenance window not found")
    cancel_window(window)
    db.commit()
