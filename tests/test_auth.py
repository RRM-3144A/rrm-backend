import pytest

from app import security
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
    payload = decode_access_token(response.json()["access_token"])
    assert payload["sub"] == "ana.pop@student.usv.ro"


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
    token = security.create_access_token("ana.pop@student.usv.ro")

    with pytest.raises(AuthError):
        decode_access_token(token[:-2] + "xx")
