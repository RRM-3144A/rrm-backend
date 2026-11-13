from fastapi import APIRouter, HTTPException, status

from app.schemas import GoogleLoginRequest, TokenResponse
from app.security import AuthError, create_access_token, verify_google_token

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/google", response_model=TokenResponse)
def login_with_google(body: GoogleLoginRequest) -> TokenResponse:
    try:
        identity = verify_google_token(body.id_token)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return TokenResponse(access_token=create_access_token(identity.email))
