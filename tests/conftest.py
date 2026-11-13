import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (registers the tables)
from app.database import Base, get_db
from app.models import Role, User
from app.security import create_access_token
from app.main import app


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _make_engine():
    """In-memory SQLite by default; set TEST_DATABASE_URL to run against PostgreSQL."""
    if TEST_DATABASE_URL:
        return create_engine(TEST_DATABASE_URL)
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


@pytest.fixture
def db():
    engine = _make_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db):
    counter = iter(range(1, 10_000))

    def _make_user(role: Role = Role.STUDENT, **fields) -> User:
        n = next(counter)
        user = User(
            email=fields.pop("email", f"user{n}@student.usv.ro"),
            first_name=fields.pop("first_name", f"User{n}"),
            last_name=fields.pop("last_name", "Test"),
            role=role,
            **fields,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make_user


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.fixture
def student(make_user):
    return make_user(Role.STUDENT)


@pytest.fixture
def admin(make_user):
    return make_user(Role.ADMIN)
