import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan


@pytest.fixture
async def client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def _register(client, name="Test Athlete"):
    email = f"athlete_{uuid.uuid4().hex[:8]}@fittrack.io"
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strongPassword123!", "full_name": name},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    return email, {"Authorization": f"Bearer {data['access_token']}"}, data["user"]


async def test_health_reports_database(client):
    res = await client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["database_connected"] is True
    assert data["database"]


async def test_login_rejects_wrong_password_and_unknown_user(client):
    email, _, _ = await _register(client)
    ok = await client.post("/api/v1/auth/login", json={"email": email, "password": "strongPassword123!"})
    assert ok.status_code == 200
    bad = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrongpass"})
    assert bad.status_code == 401
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@fittrack.io", "password": "password123"}
    )
    assert unknown.status_code == 401


async def test_register_duplicate_email_rejected(client):
    email, _, _ = await _register(client)
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "another123", "full_name": "Dup"},
    )
    assert res.status_code == 400


async def test_google_endpoint_does_not_trust_raw_email(client):
    # Previously anyone could sign in as any email; now an ID token is required
    res = await client.post("/api/v1/auth/google", json={"email": "victim@gmail.com"})
    assert res.status_code in (400, 503)


async def test_google_start_without_config_returns_error_deep_link(client):
    res = await client.get("/api/v1/auth/google/start?app_state=abc")
    assert res.status_code == 200
    assert "fittrack://auth/google?error=google_not_configured" in res.text


async def test_protected_routes_require_auth(client):
    for path in ("/api/v1/dashboard/today", "/api/v1/vitals/daily", "/api/v1/nutrition/today"):
        assert (await client.get(path)).status_code == 401


async def test_new_user_starts_with_real_empty_data(client):
    _, headers, user = await _register(client, "Fresh User")
    assert user["is_onboarded"] is False

    dash = (await client.get("/api/v1/dashboard/today", headers=headers)).json()
    assert dash["user_name"] == "Fresh User"
    assert dash["steps_today"] == 0
    assert dash["workout_minutes_week"] == 0
    assert dash["nutrients_summary"]["calories_consumed"] == 0
    assert [c["title"] for c in dash["activity_cards"]] == ["Running", "Skateboard"]
    assert all(c["action_label"] == "Start" for c in dash["activity_cards"])

    vitals = (await client.get("/api/v1/vitals/daily", headers=headers)).json()
    assert vitals["steps_count"] == 0
    assert vitals["latest_hr_bpm"] == 0

    nutr = (await client.get("/api/v1/nutrition/today", headers=headers)).json()
    assert nutr["calories_consumed"] == 0
    assert nutr["water_liters"] == 0
    assert nutr["meals"] == []

    hr = (await client.get("/api/v1/vitals/heart-rate-zones", headers=headers)).json()
    assert hr["chart_bars"] == []
    assert hr["readings_today"] == 0


async def test_onboarding_updates_profile(client):
    _, headers, _ = await _register(client)
    res = await client.put(
        "/api/v1/auth/onboarding",
        headers=headers,
        json={"age": 30, "weight_kg": 80.0, "height_cm": 180.0, "primary_goal": "Endurance"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_onboarded"] is True
    assert data["target_hr_bpm"] == round((220 - 30) * 0.7)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["weight_kg"] == 80.0


async def test_steps_sync_is_additive_and_concurrent_safe(client):
    _, headers, _ = await _register(client)
    # Simulates the app's live polling + step sync firing at the same moment
    results = await asyncio.gather(
        *[
            client.patch("/api/v1/vitals/steps", headers=headers, json={"steps_increment": 10})
            for _ in range(5)
        ],
        client.get("/api/v1/vitals/daily", headers=headers),
        client.get("/api/v1/dashboard/today", headers=headers),
    )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    vitals = (await client.get("/api/v1/vitals/daily", headers=headers)).json()
    assert vitals["steps_count"] == 50


async def test_timezone_header_picks_device_day(client):
    _, headers, _ = await _register(client)
    # +14h zone vs -12h zone are always on different calendar days
    east = {**headers, "X-TZ-Offset-Minutes": "-840"}
    west = {**headers, "X-TZ-Offset-Minutes": "720"}
    await client.patch("/api/v1/vitals/steps", headers=east, json={"steps_increment": 100})
    e = (await client.get("/api/v1/vitals/daily", headers=east)).json()
    w = (await client.get("/api/v1/vitals/daily", headers=west)).json()
    assert e["date"] != w["date"]
    assert e["steps_count"] == 100 and w["steps_count"] == 0


async def test_weight_update_and_status(client):
    _, headers, _ = await _register(client)
    res = await client.put("/api/v1/vitals/daily", headers=headers, json={"weight_kg": 70.5})
    assert res.status_code == 200
    assert res.json()["weight_kg"] == 70.5
    assert res.json()["weight_status"] == "First Reading"
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["weight_kg"] == 70.5


async def test_heart_rate_logging_flows_to_screens(client):
    _, headers, _ = await _register(client)
    for i, bpm in enumerate([90, 120, 150, 110, 95, 130, 140, 100]):
        res = await client.post(
            "/api/v1/vitals/heart-rate-log",
            headers=headers,
            json={"slot_label": f"1{i}:00", "bpm_value": bpm},
        )
        assert res.status_code == 201
    hr = (await client.get("/api/v1/vitals/heart-rate-zones", headers=headers)).json()
    assert len(hr["chart_bars"]) == 7  # last 7 readings
    assert hr["chart_bars"][-1]["bpm_value"] == 100
    assert hr["latest_hr_bpm"] == 100
    assert hr["readings_today"] == 8
    assert hr["max_bpm_today"] == 150
    assert sum(1 for b in hr["chart_bars"] if b["is_peak"]) == 1
    vitals = (await client.get("/api/v1/vitals/daily", headers=headers)).json()
    assert vitals["latest_hr_bpm"] == 100


async def test_nutrition_meals_and_water(client):
    _, headers, _ = await _register(client)
    water = await client.post("/api/v1/nutrition/hydration", headers=headers)
    assert water.json()["water_liters"] == 0.25

    meal = await client.post(
        "/api/v1/nutrition/meals",
        headers=headers,
        json={"meal_type": "Lunch", "title": "Chicken Rice", "calories": 600,
              "protein_g": 40, "carbs_g": 70, "fats_g": 15},
    )
    assert meal.status_code == 201
    meal_id = meal.json()["id"]

    nutr = (await client.get("/api/v1/nutrition/today", headers=headers)).json()
    assert nutr["calories_consumed"] == 600
    assert (nutr["protein_g"], nutr["carbs_g"], nutr["fats_g"]) == (40, 70, 15)
    assert len(nutr["meals"]) == 1
    assert nutr["metabolic_score_pct"] > 0

    dash = (await client.get("/api/v1/dashboard/today", headers=headers)).json()
    assert dash["nutrients_summary"]["calories_consumed"] == 600

    assert (await client.delete(f"/api/v1/nutrition/meals/{meal_id}", headers=headers)).status_code == 204
    nutr = (await client.get("/api/v1/nutrition/today", headers=headers)).json()
    assert nutr["calories_consumed"] == 0 and nutr["carbs_g"] == 0


async def test_workout_lifecycle_updates_dashboard(client):
    _, headers, _ = await _register(client)
    start = await client.post(
        "/api/v1/workouts/start", headers=headers,
        json={"title": "Running", "category": "Sports", "target_duration_seconds": 1800},
    )
    assert start.status_code == 201
    wid = start.json()["id"]

    # Starting again resumes the same session instead of creating a duplicate
    again = await client.post("/api/v1/workouts/start", headers=headers, json={"title": "Running"})
    assert again.json()["id"] == wid

    tick = await client.patch(
        f"/api/v1/workouts/{wid}/tick", headers=headers,
        json={"duration_seconds": 900, "distance_km": 2.4, "calories_burned": 180,
              "steps_count": 2600, "status": "paused"},
    )
    assert tick.status_code == 200
    assert tick.json()["progress_pct"] == 50
    assert tick.json()["status"] == "paused"

    active = (await client.get("/api/v1/workouts/active", headers=headers)).json()
    assert active["id"] == wid

    dash = (await client.get("/api/v1/dashboard/today", headers=headers)).json()
    running = dash["activity_cards"][0]
    assert running["action_label"] == "Continue" and running["progress_pct"] == 50
    assert dash["workout_minutes_week"] == 15

    done = await client.post(f"/api/v1/workouts/{wid}/complete", headers=headers)
    assert done.json()["status"] == "completed"
    dash = (await client.get("/api/v1/dashboard/today", headers=headers)).json()
    assert dash["workouts_completed_week"] == 1
    assert dash["total_calories_burned"] == 180
    assert dash["activity_cards"][0]["action_label"] == "Start"

    late_tick = await client.patch(f"/api/v1/workouts/{wid}/tick", headers=headers, json={"duration_seconds": 1})
    assert late_tick.status_code == 409


async def test_users_cannot_see_each_others_data(client):
    _, h1, _ = await _register(client)
    _, h2, _ = await _register(client)
    meal = await client.post(
        "/api/v1/nutrition/meals", headers=h1,
        json={"meal_type": "Dinner", "title": "Private meal", "calories": 500},
    )
    assert (await client.delete(f"/api/v1/nutrition/meals/{meal.json()['id']}", headers=h2)).status_code == 404
    assert (await client.get("/api/v1/nutrition/today", headers=h2)).json()["meals"] == []
