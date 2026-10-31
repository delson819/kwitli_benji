from datetime import date, timedelta


def _register(client, email):
    response = client.post("/api/v1/auth/register", json={
        "email": email, "password": "ClaveSegura123!", "first_name": "Marchand",
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_article_and_availability_creation_keep_independent_statuses(client):
    merchant = _register(client, "catalog-owner@example.co")
    other = _register(client, "catalog-other@example.co")
    profile = client.post("/api/v1/cooks", json={
        "display_name": "Restaurant test", "latitude": 14.7, "longitude": -17.4,
    }, headers=merchant)
    assert profile.status_code == 201

    article = client.post("/api/v1/dishes", json={
        "name": "Poulet yassa", "description": "Plat du jour", "price": "4500",
        "currency": "XOF", "category": "Plats", "is_active": False,
    }, headers=merchant)
    assert article.status_code == 201
    article_id = article.json()["id"]
    assert article.json()["category"] == "Plats"
    assert article.json()["is_active"] is False
    assert not any(row["dish_id"] == article_id for row in client.get("/api/v1/availabilities", headers=merchant).json())

    window = {"dish_id": article_id, "available_date": str(date.today() + timedelta(days=2)),
              "start_time": "11:00", "end_time": "14:00", "total_portions": 8}
    first = client.post("/api/v1/availabilities", json={**window, "status": "inactive"}, headers=merchant)
    second = client.post("/api/v1/availabilities", json={**window, "start_time": "17:00", "end_time": "21:00"}, headers=merchant)
    assert first.status_code == second.status_code == 201
    first_id, second_id = first.json()["id"], second.json()["id"]
    assert first_id != second_id
    assert first.json()["status"] == "inactive"
    assert second.json()["status"] == "active"

    assert client.patch(f"/api/v1/dishes/{article_id}", json={"is_active": True}, headers=other).status_code == 403
    assert client.patch(f"/api/v1/availabilities/{first_id}", json={"status": "active"}, headers=other).status_code == 403
    assert client.patch(f"/api/v1/dishes/{article_id}", json={"is_active": True}, headers=merchant).status_code == 200
    assert client.patch(f"/api/v1/availabilities/{first_id}", json={"status": "active"}, headers=merchant).status_code == 200
    assert client.get(f"/api/v1/availabilities/{second_id}", headers=merchant).json()["status"] == "active"
    assert client.get(f"/api/v1/dishes/{article_id}", headers=merchant).json()["is_active"] is True


def test_creation_rejects_invalid_initial_availability_status(client):
    merchant = _register(client, "catalog-invalid@example.co")
    assert client.post("/api/v1/cooks", json={
        "display_name": "Restaurant test", "latitude": 14.7, "longitude": -17.4,
    }, headers=merchant).status_code == 201
    article = client.post("/api/v1/dishes", json={
        "name": "Poulet yassa", "description": "Plat du jour", "price": "4500", "currency": "XOF",
    }, headers=merchant)
    assert article.status_code == 201
    response = client.post("/api/v1/availabilities", json={
        "dish_id": article.json()["id"], "available_date": str(date.today() + timedelta(days=2)),
        "start_time": "11:00", "end_time": "14:00", "total_portions": 8, "status": "deleted",
    }, headers=merchant)
    assert response.status_code == 422
