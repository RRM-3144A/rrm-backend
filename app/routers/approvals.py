from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_admin
from app.models import User
from app.schemas import TeamUsageOut
from app.services.approvals import get_team_resource_usage

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("/usage", response_model=list[TeamUsageOut])
def read_team_resource_usage(
    start_date: date | None = None,
    end_date: date | None = None,
    resource_id: int | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> list[TeamUsageOut]:
    """Approved and completed reservation counts and hours per team for resources managed by the admin."""
    return get_team_resource_usage(
        db,
        admin,
        start_date=start_date,
        end_date=end_date,
        resource_id=resource_id,
    )