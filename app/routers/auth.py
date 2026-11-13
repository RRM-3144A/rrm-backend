from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import GoogleLoginRequest, TokenResponse, UserOut
from app.security import AuthError, create_access_token, verify_google_token
from app.services.users import get_or_create_user

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/google", response_model=TokenResponse)
def login_with_google(body: GoogleLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        identity = verify_google_token(body.id_token)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = get_or_create_user(db, identity)
    token = create_access_token(str(user.id), {"role": user.role.value})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def read_current_user(user: User = Depends(get_current_user)) -> User:
    return user
