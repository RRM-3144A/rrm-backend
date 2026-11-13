from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Resource, ResourceCategory, ResourceStatus, Role, User
from app.schemas import ResourceCreate, ResourceOut, ResourceUpdate

router = APIRouter(prefix="/resources", tags=["Resources"])


def get_resource_or_404(db: Session, resource_id: int) -> Resource:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
    return resource


def _check_category(db: Session, category_id: int) -> None:
    if db.get(ResourceCategory, category_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Category not found")


def _load_admins(db: Session, admin_ids: list[int]) -> list[User]:
    admins = list(db.scalars(select(User).where(User.id.in_(admin_ids))))
    if len(admins) != len(set(admin_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown administrator id")
    if any(admin.role != Role.ADMIN for admin in admins):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Resource administrators must have the ADMIN role"
        )
    return admins


@router.get("", response_model=list[ResourceOut])
def list_resources(
    category_id: int | None = None,
    resource_status: ResourceStatus | None = Query(default=None, alias="status"),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Resource]:
    query = select(Resource).order_by(Resource.name)
    if category_id is not None:
        query = query.where(Resource.category_id == category_id)
    if resource_status is not None:
        query = query.where(Resource.status == resource_status)
    elif not (include_inactive and user.role == Role.ADMIN):
        query = query.where(Resource.status != ResourceStatus.INACTIVE)
    return list(db.scalars(query))


@router.get("/{resource_id}", response_model=ResourceOut)
def read_resource(
    resource_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Resource:
    return get_resource_or_404(db, resource_id)


@router.post("", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
def create_resource(
    body: ResourceCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> Resource:
    _check_category(db, body.category_id)
    fields = body.model_dump(exclude={"admin_ids"})
    resource = Resource(**fields)
    resource.admins = _load_admins(db, body.admin_ids) if body.admin_ids else [admin]
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.patch("/{resource_id}", response_model=ResourceOut)
def update_resource(
    resource_id: int,
    body: ResourceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> Resource:
    resource = get_resource_or_404(db, resource_id)
    changes = body.model_dump(exclude_unset=True)
    if "category_id" in changes:
        _check_category(db, changes["category_id"])
    if "admin_ids" in changes:
        resource.admins = _load_admins(db, changes.pop("admin_ids") or [])
    for field, value in changes.items():
        setattr(resource, field, value)
    db.commit()
    db.refresh(resource)
    return resource


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_resource(
    resource_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> None:
    """Deactivates the resource instead of deleting it, so its reservation history is kept."""
    resource = get_resource_or_404(db, resource_id)
    resource.status = ResourceStatus.INACTIVE
    db.commit()
