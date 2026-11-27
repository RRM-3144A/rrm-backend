from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import DemoLoginRequest, GoogleLoginRequest, TokenResponse, UserOut
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


@router.post("/demo", response_model=TokenResponse)
def login_demo(body: DemoLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Signs in as an existing user by e-mail, without Google (DEMO_LOGIN=true only).

    Used for the presentation and local development when no Google OAuth client is
    configured. The institutional-domain rule still applies.
    """
    if not settings.demo_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    email = body.email.strip().lower()
    if not email.endswith("@" + settings.allowed_email_domain):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Only @{settings.allowed_email_domain} accounts can sign in",
        )
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown demo account")
    token = create_access_token(str(user.id), {"role": user.role.value})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def read_current_user(user: User = Depends(get_current_user)) -> User:
    return user
