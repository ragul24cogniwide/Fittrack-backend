import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.main import app, lifespan
from app.models.activity import DailyVitals
from app.models.nutrition import NutritionLog
from app.models.user import User

UTC = {"X-TZ-Offset-Minutes": "0"}


@pytest.fixture
async def client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def _register(client):
    email = f"hist_{uuid.uuid4().hex[:8]}@fittrack.io"
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strongPassword123!", "full_name": "History User"},
    )
    assert res.status_code == 201, res.text
    return email, {"Authorization": f"Bearer {res.json()['access_token']}", **UTC}


async def _seed_past(email: str, rows):
    """rows: list of (days_ago, steps, weight, calories)"""
    today = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        for days_ago, steps, weight, kcal in rows:
            d = today - timedelta(days=days_ago)
            db.add(DailyVitals(user_id=user.id, date=d, steps_count=steps, weight_kg=weight))
            if kcal:
                db.add(NutritionLog(user_id=user.id, date=d, calories_consumed=kcal))
        await db.commit()


async def test_steps_go_to_their_own_day(client):
    _, headers = await _register(client)
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    too_old = (datetime.now(timezone.utc).date() - timedelta(days=31)).isoformat()

    ok = await client.patch(
        "/api/v1/vitals/steps", headers=headers, json={"steps_increment": 40, "for_date": yesterday}
    )
    assert ok.status_code == 200 and ok.json()["date"] == yesterday
    bad = await client.patch(
        "/api/v1/vitals/steps", headers=headers, json={"steps_increment": 40, "for_date": too_old}
    )
    assert bad.status_code == 400

    # Today starts fresh: yesterday's steps don't carry over (the midnight reset)
    today_vitals = (await client.get("/api/v1/vitals/daily", headers=headers)).json()
    assert today_vitals["steps_count"] == 0


async def test_history_summary_fills_every_day(client):
    email, headers = await _register(client)
    await _seed_past(email, [(3, 12000, 70.0, 2100), (1, 5000, 69.6, 0)])
    await client.patch("/api/v1/vitals/steps", headers=headers, json={"steps_increment": 100})
    await client.post(
        "/api/v1/nutrition/meals", headers=headers,
        json={"meal_type": "Lunch", "title": "Rice bowl", "calories": 600},
    )
    w = (await client.post("/api/v1/workouts/start", headers=headers, json={"title": "Running"})).json()
    await client.patch(f"/api/v1/workouts/{w['id']}/tick", headers=headers,
                       json={"duration_seconds": 1200, "calories_burned": 200})
    await client.post(f"/api/v1/workouts/{w['id']}/complete", headers=headers)

    res = await client.get("/api/v1/history/summary?days=7", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()
    days = data["days"]
    assert len(days) == 7
    assert days[0]["date"] < days[-1]["date"]  # oldest first
    by_ago = {6 - i: d for i, d in enumerate(days)}
    assert by_ago[3]["steps_count"] == 12000 and by_ago[3]["calories_consumed"] == 2100
    assert by_ago[3]["distance_km"] > 0
    assert by_ago[1]["steps_count"] == 5000 and by_ago[1]["weight_kg"] == 69.6
    assert by_ago[2]["steps_count"] == 0 and by_ago[2]["weight_kg"] is None  # no data that day
    assert by_ago[0]["steps_count"] == 100
    assert by_ago[0]["workouts"] == 1 and by_ago[0]["workout_minutes"] == 20

    t = data["totals"]
    assert t["steps"] == 17100
    assert t["best_steps"] == 12000
    assert t["days_step_goal_met"] == 1
    assert t["workouts"] == 1 and t["workout_calories"] == 200
    assert t["avg_calories_consumed"] == (2100 + 600) // 2


async def test_day_detail_lists_everything_for_that_day(client):
    email, headers = await _register(client)
    await _seed_past(email, [(2, 8000, 71.0, 0)])
    await client.post("/api/v1/nutrition/meals", headers=headers,
                      json={"meal_type": "Dinner", "title": "Dal and rice", "calories": 550})
    await client.post("/api/v1/vitals/heart-rate-log", headers=headers,
                      json={"slot_label": "09:00", "bpm_value": 88})
    await client.post("/api/v1/workouts/start", headers=headers, json={"title": "Skateboard"})

    today = datetime.now(timezone.utc).date()
    detail = (await client.get(f"/api/v1/history/day/{today.isoformat()}", headers=headers)).json()
    assert [m["title"] for m in detail["meals"]] == ["Dal and rice"]
    assert [w["title"] for w in detail["workouts"]] == ["Skateboard"]
    assert [r["bpm_value"] for r in detail["heart_rate"]] == [88]
    assert detail["summary"]["avg_hr_bpm"] == 88

    past = (await client.get(f"/api/v1/history/day/{(today - timedelta(days=2)).isoformat()}",
                             headers=headers)).json()
    assert past["summary"]["steps_count"] == 8000
    assert past["meals"] == [] and past["workouts"] == []

    future = await client.get(f"/api/v1/history/day/{(today + timedelta(days=2)).isoformat()}",
                              headers=headers)
    assert future.status_code == 400


async def test_history_is_private_per_user(client):
    email, _ = await _register(client)
    await _seed_past(email, [(1, 9999, 70.0, 0)])
    _, other = await _register(client)
    data = (await client.get("/api/v1/history/summary?days=7", headers=other)).json()
    assert data["totals"]["steps"] == 0
