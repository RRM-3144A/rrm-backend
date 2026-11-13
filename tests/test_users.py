from app.models import Team
from tests.conftest import auth_headers


def test_student_cannot_list_users(client, student):
    response = client.get("/users", headers=auth_headers(student))

    assert response.status_code == 403


def test_admin_can_list_users(client, admin, student):
    response = client.get("/users", headers=auth_headers(admin))

    assert response.status_code == 200
    assert {u["id"] for u in response.json()} == {admin.id, student.id}


def test_admin_can_promote_a_student(client, admin, student):
    response = client.patch(
        f"/users/{student.id}", json={"role": "ADMIN"}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN"


def test_admin_cannot_demote_themselves(client, admin):
    response = client.patch(
        f"/users/{admin.id}", json={"role": "STUDENT"}, headers=auth_headers(admin)
    )

    assert response.status_code == 409


def test_admin_assigns_team(client, db, admin, student):
    team = Team(name="Robotics")
    db.add(team)
    db.commit()

    response = client.patch(
        f"/users/{student.id}", json={"team_id": team.id}, headers=auth_headers(admin)
    )

    assert response.json()["team"] == {"id": team.id, "name": "Robotics"}


def test_unknown_team_is_rejected(client, admin, student):
    response = client.patch(
        f"/users/{student.id}", json={"team_id": 999}, headers=auth_headers(admin)
    )

    assert response.status_code == 422


def test_only_admin_creates_teams(client, admin, student):
    assert client.post("/teams", json={"name": "AI"}, headers=auth_headers(student)).status_code == 403
    assert client.post("/teams", json={"name": "AI"}, headers=auth_headers(admin)).status_code == 201
    assert client.post("/teams", json={"name": "AI"}, headers=auth_headers(admin)).status_code == 409
