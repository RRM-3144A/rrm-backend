import pytest

from app.models import Resource, ResourceCategory, ResourceStatus
from tests.conftest import auth_headers


@pytest.fixture
def category(db):
    category = ResourceCategory(name="Imprimante 3D")
    db.add(category)
    db.commit()
    return category


def _create(client, admin, category, **fields):
    body = {"name": "Prusa MK4", "category_id": category.id, **fields}
    return client.post("/resources", json=body, headers=auth_headers(admin))


def test_admin_creates_resource_and_becomes_its_admin(client, admin, category):
    response = _create(client, admin, category, max_concurrent_teams=2, requires_training=True)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["max_concurrent_teams"] == 2
    assert body["category"]["name"] == "Imprimante 3D"
    assert [a["id"] for a in body["admins"]] == [admin.id]


def test_student_cannot_create_resource(client, student, category):
    response = client.post(
        "/resources", json={"name": "X", "category_id": category.id}, headers=auth_headers(student)
    )

    assert response.status_code == 403


@pytest.mark.parametrize("teams", [0, 3])
def test_max_concurrent_teams_must_be_1_or_2(client, admin, category, teams):
    assert _create(client, admin, category, max_concurrent_teams=teams).status_code == 422


def test_missing_name_is_422(client, admin, category):
    response = client.post(
        "/resources", json={"category_id": category.id}, headers=auth_headers(admin)
    )

    assert response.status_code == 422


def test_unknown_category_is_422(client, admin):
    response = client.post(
        "/resources", json={"name": "X", "category_id": 999}, headers=auth_headers(admin)
    )

    assert response.status_code == 422


def test_resource_admins_must_be_admins(client, admin, student, category):
    assert _create(client, admin, category, admin_ids=[student.id]).status_code == 422


def test_list_filters_by_category(client, db, student, category):
    rooms = ResourceCategory(name="Săli")
    db.add(rooms)
    db.flush()
    db.add_all(
        [Resource(name="Prusa", category_id=category.id), Resource(name="C201", category_id=rooms.id)]
    )
    db.commit()

    response = client.get(f"/resources?category_id={rooms.id}", headers=auth_headers(student))

    assert [r["name"] for r in response.json()] == ["C201"]


def test_deactivated_resources_are_hidden_from_students(client, db, admin, student, category):
    resource_id = _create(client, admin, category).json()["id"]

    assert client.delete(f"/resources/{resource_id}", headers=auth_headers(admin)).status_code == 204

    assert client.get("/resources", headers=auth_headers(student)).json() == []
    admin_view = client.get("/resources?include_inactive=true", headers=auth_headers(admin)).json()
    assert admin_view[0]["status"] == "INACTIVE"
    assert db.get(Resource, resource_id) is not None


def test_admin_updates_status_and_capacity(client, admin, category):
    resource_id = _create(client, admin, category).json()["id"]

    response = client.patch(
        f"/resources/{resource_id}",
        json={"status": "MAINTENANCE", "max_concurrent_teams": 2},
        headers=auth_headers(admin),
    )

    assert response.json()["status"] == ResourceStatus.MAINTENANCE.value
    assert response.json()["max_concurrent_teams"] == 2


def test_unknown_resource_is_404(client, student):
    assert client.get("/resources/999", headers=auth_headers(student)).status_code == 404
