from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import Resource, ResourceCategory, User
from app.schemas import CategoryCreate, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["Categories"])


def _to_out(db: Session, category: ResourceCategory) -> CategoryOut:
    count = db.scalar(select(func.count()).where(Resource.category_id == category.id))
    return CategoryOut(
        id=category.id,
        name=category.name,
        description=category.description,
        resource_count=count or 0,
    )


def _get_or_404(db: Session, category_id: int) -> ResourceCategory:
    category = db.get(ResourceCategory, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category


def _commit_unique_name(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A category with this name already exists"
        ) from exc


@router.get("", response_model=list[CategoryOut])
def list_categories(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[CategoryOut]:
    categories = db.scalars(select(ResourceCategory).order_by(ResourceCategory.name))
    return [_to_out(db, category) for category in categories]


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> CategoryOut:
    category = ResourceCategory(name=body.name.strip(), description=body.description)
    db.add(category)
    _commit_unique_name(db)
    return _to_out(db, category)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> CategoryOut:
    category = _get_or_404(db, category_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name"):
        category.name = changes["name"].strip()
    if "description" in changes:
        category.description = changes["description"]
    _commit_unique_name(db)
    return _to_out(db, category)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> None:
    category = _get_or_404(db, category_id)
    if db.scalar(select(func.count()).where(Resource.category_id == category.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The category still has resources and cannot be deleted"
        )
    db.delete(category)
    db.commit()
