from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Role, User
from app.security import GoogleIdentity


def get_or_create_user(db: Session, identity: GoogleIdentity) -> User:
    """Returns the user for a Google identity, creating it on the first sign-in.

    Users are matched by Google subject first, then by e-mail, so an account that was
    added by e-mail before its first login is linked instead of duplicated.
    """
    user = db.scalar(select(User).where(User.google_sub == identity.sub))
    if user is None:
        user = db.scalar(select(User).where(User.email == identity.email))
    if user is None:
        user = User(
            email=identity.email,
            first_name=identity.first_name,
            last_name=identity.last_name,
            role=Role.STUDENT,
        )
        db.add(user)

    user.google_sub = identity.sub
    if identity.email in settings.admin_email_set:
        user.role = Role.ADMIN
    db.commit()
    db.refresh(user)
    return user
