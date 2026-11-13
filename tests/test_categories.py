from app.models import Resource, ResourceCategory
from tests.conftest import auth_headers


def test_signed_in_user_lists_categories_with_resource_count(client, db, student):
    lab = ResourceCategory(name="Imprimante 3D")
    db.add(lab)
    db.flush()
    db.add(Resource(name="Prusa MK4", category_id=lab.id))
    db.commit()

    response = client.get("/categories", headers=auth_headers(student))

    assert response.status_code == 200
    assert response.json() == [
        {"id": lab.id, "name": "Imprimante 3D", "description": None, "resource_count": 1}
    ]


def test_anonymous_cannot_list_categories(client):
    assert client.get("/categories").status_code == 401


def test_student_cannot_create_category(client, student):
    response = client.post("/categories", json={"name": "Roboți"}, headers=auth_headers(student))

    assert response.status_code == 403


def test_admin_creates_updates_and_deletes_category(client, admin):
    headers = auth_headers(admin)

    created = client.post("/categories", json={"name": "Roboți"}, headers=headers)
    assert created.status_code == 201
    category_id = created.json()["id"]

    updated = client.patch(
        f"/categories/{category_id}", json={"description": "Brațe robotice"}, headers=headers
    )
    assert updated.json()["description"] == "Brațe robotice"

    assert client.delete(f"/categories/{category_id}", headers=headers).status_code == 204
    assert client.get("/categories", headers=headers).json() == []


def test_duplicate_category_name_is_409(client, admin):
    headers = auth_headers(admin)
    client.post("/categories", json={"name": "Săli"}, headers=headers)

    response = client.post("/categories", json={"name": "Săli"}, headers=headers)

    assert response.status_code == 409


def test_category_with_resources_cannot_be_deleted(client, db, admin):
    category = ResourceCategory(name="Săli")
    db.add(category)
    db.flush()
    db.add(Resource(name="C201", category_id=category.id))
    db.commit()

    response = client.delete(f"/categories/{category.id}", headers=auth_headers(admin))

    assert response.status_code == 409


def test_unknown_category_is_404(client, admin):
    response = client.patch("/categories/999", json={"name": "X"}, headers=auth_headers(admin))

    assert response.status_code == 404
