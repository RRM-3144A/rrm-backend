from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import settings


class AuthError(Exception):
    """Raised when a Google ID token or an access token is not valid."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    first_name: str
    last_name: str


def verify_google_token(token: str) -> GoogleIdentity:
    """Validates a Google ID token and returns the identity it carries.

    Only verified e-mail addresses from the allowed institutional domain are accepted.
    """
    if not settings.google_client_id:
        raise AuthError("Google sign-in is not configured")
    try:
        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.google_client_id
        )
    except ValueError as exc:
        raise AuthError("Invalid Google token") from exc

    email = str(claims.get("email", "")).lower()
    if not claims.get("email_verified"):
        raise AuthError("Google e-mail address is not verified")
    if not email.endswith("@" + settings.allowed_email_domain):
        raise AuthError(f"Only @{settings.allowed_email_domain} accounts can sign in")

    return GoogleIdentity(
        sub=str(claims["sub"]),
        email=email,
        first_name=claims.get("given_name") or email.split("@")[0],
        last_name=claims.get("family_name") or "",
    )


def create_access_token(subject: str, extra_claims: dict | None = None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired session") from exc
