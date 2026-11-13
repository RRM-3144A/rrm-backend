import pytest

from app import security
from app.models import User
from app.security import AuthError, decode_access_token


def _claims(email="ana.pop@student.usv.ro", verified=True):
    return {
        "sub": "google-123",
        "email": email,
        "email_verified": verified,
        "given_name": "Ana",
        "family_name": "Pop",
    }


@pytest.fixture
def google_claims(monkeypatch):
    monkeypatch.setattr(security.settings, "google_client_id", "test-client")
    claims = {}

    def fake_verify(token, request, audience):
        if token != "valid":
            raise ValueError("bad token")
        return claims

    monkeypatch.setattr(security.id_token, "verify_oauth2_token", fake_verify)
    return claims


def test_valid_institutional_token_returns_jwt(client, google_claims):
    google_claims.update(_claims())

    response = client.post("/auth/google", json={"id_token": "valid"})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "ana.pop@student.usv.ro"
    assert body["user"]["role"] == "STUDENT"
    assert decode_access_token(body["access_token"])["sub"] == str(body["user"]["id"])


def test_invalid_token_is_rejected(client, google_claims):
    response = client.post("/auth/google", json={"id_token": "forged"})

    assert response.status_code == 401


def test_other_domain_is_rejected(client, google_claims):
    google_claims.update(_claims(email="ana@gmail.com"))

    response = client.post("/auth/google", json={"id_token": "valid"})

    assert response.status_code == 401
    assert "student.usv.ro" in response.json()["detail"]


def test_unverified_email_is_rejected(client, google_claims):
    google_claims.update(_claims(verified=False))

    response = client.post("/auth/google", json={"id_token": "valid"})

    assert response.status_code == 401


def test_tampered_access_token_is_rejected():
    token = security.create_access_token("1")

    with pytest.raises(AuthError):
        decode_access_token(token[:-2] + "xx")


def test_first_login_creates_user_and_second_login_reuses_it(client, db, google_claims):
    google_claims.update(_claims())

    first = client.post("/auth/google", json={"id_token": "valid"}).json()
    second = client.post("/auth/google", json={"id_token": "valid"}).json()

    assert first["user"]["id"] == second["user"]["id"]
    assert db.query(User).count() == 1


def test_admin_emails_get_admin_role(client, google_claims, monkeypatch):
    monkeypatch.setattr(security.settings, "admin_emails", "ana.pop@student.usv.ro")
    google_claims.update(_claims())

    response = client.post("/auth/google", json={"id_token": "valid"})

    assert response.json()["user"]["role"] == "ADMIN"


def test_me_returns_the_signed_in_user(client, google_claims):
    google_claims.update(_claims())
    token = client.post("/auth/google", json={"id_token": "valid"}).json()["access_token"]

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["first_name"] == "Ana"


def test_me_without_token_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_expired_token_is_401(client, monkeypatch):
    monkeypatch.setattr(security.settings, "jwt_expire_minutes", -1)
    token = security.create_access_token("1")

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
