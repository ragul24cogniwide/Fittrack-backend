"""Gender in the profile, the private log (men) and the period tracker (women)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, text

from app.db.migrate import add_missing_columns
from app.main import app, lifespan

UTC = {"X-TZ-Offset-Minutes": "0"}


@pytest.fixture
async def client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def _register(client, gender=None):
    body = {
        "email": f"w_{uuid.uuid4().hex[:8]}@fittrack.io",
        "password": "strongPassword123!",
        "full_name": "Tester",
    }
    if gender:
        body["gender"] = gender
    res = await client.post("/api/v1/auth/register", json=body)
    assert res.status_code == 201, res.text
    assert res.json()["user"]["gender"] == gender
    return {"Authorization": f"Bearer {res.json()['access_token']}", **UTC}


def _today():
    return datetime.now(timezone.utc).date()


def test_migration_adds_gender_to_old_users_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR PRIMARY KEY, email VARCHAR)"))
        conn.execute(text("INSERT INTO users VALUES ('1', 'old@fittrack.io')"))
        add_missing_columns(conn)
        add_missing_columns(conn)  # safe to run on every start
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "gender" in cols


async def test_gender_set_later_and_trackers_are_per_gender(client):
    h = await _register(client)  # e.g. a Google account: no gender yet
    assert (await client.get("/api/v1/masturbation/summary", headers=h)).status_code == 403
    assert (await client.get("/api/v1/cycle/summary", headers=h)).status_code == 403

    r = await client.patch("/api/v1/auth/profile", headers=h, json={"gender": "male"})
    assert r.status_code == 200 and r.json()["gender"] == "male"
    assert (await client.get("/api/v1/auth/me", headers=h)).json()["gender"] == "male"
    assert (await client.get("/api/v1/masturbation/summary", headers=h)).status_code == 200
    assert (await client.get("/api/v1/cycle/summary", headers=h)).status_code == 403

    r = await client.patch("/api/v1/auth/profile", headers=h, json={"gender": "robot"})
    assert r.status_code == 422

    # Onboarding can set it too, and leaves it alone when not sent
    r = await client.put("/api/v1/auth/onboarding", headers=h, json={
        "age": 30, "weight_kg": 60, "height_cm": 165, "primary_goal": "Endurance"})
    assert r.json()["gender"] == "male"
    r = await client.put("/api/v1/auth/onboarding", headers=h, json={
        "age": 30, "weight_kg": 60, "height_cm": 165, "primary_goal": "Endurance", "gender": "female"})
    assert r.json()["gender"] == "female"


async def test_private_log(client):
    h = await _register(client, "male")
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)

    r = await client.post("/api/v1/masturbation/logs", headers=h, json={})
    assert r.status_code == 201, r.text
    first_id = r.json()["id"]
    # Double tap on "Log now" doesn't count twice
    r = await client.post("/api/v1/masturbation/logs", headers=h, json={})
    assert r.json()["id"] == first_id

    for days_ago in (2, 2, 6, 20):
        at = (now - timedelta(days=days_ago)).replace(hour=22, minute=15)
        r = await client.post("/api/v1/masturbation/logs", headers=h, json={"at": at.isoformat()})
        assert r.status_code == 201, r.text

    s = (await client.get("/api/v1/masturbation/summary", headers=h)).json()
    assert s["today_count"] == 1
    assert s["week_count"] == 4  # today, 2x two days ago, six days ago
    assert s["month_count"] == 5
    assert s["avg_per_week"] == 1.2
    assert s["days_since_last"] == 0
    assert s["longest_gap_days"] == 13  # between 20 and 6 days ago
    assert len(s["daily"]) == 14 and s["daily"][-1] == {"date": _today().isoformat(), "count": 1}
    assert s["daily"][-3]["count"] == 2
    assert len(s["recent"]) == 5

    # Undo
    assert (await client.delete(f"/api/v1/masturbation/logs/{first_id}", headers=h)).status_code == 204
    s = (await client.get("/api/v1/masturbation/summary", headers=h)).json()
    assert s["today_count"] == 0 and s["days_since_last"] == 2

    # Future / too old are refused
    future = (now + timedelta(hours=2)).isoformat()
    assert (await client.post("/api/v1/masturbation/logs", headers=h, json={"at": future})).status_code == 400
    old = (now - timedelta(days=40)).isoformat()
    assert (await client.post("/api/v1/masturbation/logs", headers=h, json={"at": old})).status_code == 400

    # Another user can't delete or see these
    other = await _register(client, "male")
    log_id = s["recent"][0]["id"]
    assert (await client.delete(f"/api/v1/masturbation/logs/{log_id}", headers=other)).status_code == 404
    assert (await client.get("/api/v1/masturbation/summary", headers=other)).json()["month_count"] == 0


async def test_period_tracker_predictions(client):
    h = await _register(client, "female")
    s = (await client.get("/api/v1/cycle/summary", headers=h)).json()
    assert s["periods"] == [] and s["phase"] is None and s["avg_cycle_days"] == 28
    assert "first day" in s["tip"]

    today = _today()
    d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    # Three past periods, 30 days apart, 5 days long
    for start in (70, 40, 10):
        r = await client.post("/api/v1/cycle/periods", headers=h, json={
            "start_date": d(start), "end_date": d(start - 4), "flow": "medium"})
        assert r.status_code == 201, r.text
        assert r.json()["length_days"] == 5

    s = (await client.get("/api/v1/cycle/summary", headers=h)).json()
    assert s["avg_cycle_days"] == 30 and s["avg_period_days"] == 5
    assert s["cycle_day"] == 11 and not s["on_period"]
    assert s["next_period_start"] == (today + timedelta(days=20)).isoformat()
    assert s["days_until_next"] == 20
    # Ovulation 14 days before the next period: day 16 of the cycle
    assert s["ovulation_date"] == (today + timedelta(days=6)).isoformat()
    assert s["phase"] == "follicular"
    assert [p["start_date"] for p in s["periods"]] == [d(10), d(40), d(70)]

    # Overlapping a logged period is refused
    r = await client.post("/api/v1/cycle/periods", headers=h, json={"start_date": d(8)})
    assert r.status_code == 400 and "overlaps" in r.json()["detail"]
    # Future start refused
    r = await client.post("/api/v1/cycle/periods", headers=h, json={
        "start_date": (today + timedelta(days=1)).isoformat()})
    assert r.status_code == 400


async def test_period_started_today_then_ended(client):
    h = await _register(client, "female")
    today = _today()
    r = await client.post("/api/v1/cycle/periods", headers=h, json={"start_date": (today - timedelta(days=2)).isoformat()})
    pid = r.json()["id"]
    s = (await client.get("/api/v1/cycle/summary", headers=h)).json()
    assert s["on_period"] and s["period_day"] == 3 and s["phase"] == "period"
    assert "Period day 3" in s["tip"]

    # Can't start another while this one is still going
    r = await client.post("/api/v1/cycle/periods", headers=h, json={"start_date": today.isoformat()})
    assert r.status_code == 400 and "still going" in r.json()["detail"]

    # End it today
    r = await client.patch(f"/api/v1/cycle/periods/{pid}", headers=h, json={"end_date": today.isoformat()})
    assert r.status_code == 200 and r.json()["length_days"] == 3
    s = (await client.get("/api/v1/cycle/summary", headers=h)).json()
    assert not s["on_period"] and s["cycle_day"] == 3 and s["phase"] != "period"
    # Ending before it started is refused
    r = await client.patch(f"/api/v1/cycle/periods/{pid}", headers=h, json={
        "end_date": (today - timedelta(days=5)).isoformat()})
    assert r.status_code == 400

    # Late: a single period 35 days ago with the default 28-day cycle
    h2 = await _register(client, "female")
    await client.post("/api/v1/cycle/periods", headers=h2, json={
        "start_date": (today - timedelta(days=35)).isoformat(),
        "end_date": (today - timedelta(days=31)).isoformat()})
    s = (await client.get("/api/v1/cycle/summary", headers=h2)).json()
    assert s["phase"] == "late" and s["days_until_next"] == -7
    assert "7 days later" in s["tip"]

    # Delete
    assert (await client.delete(f"/api/v1/cycle/periods/{pid}", headers=h)).status_code == 204
    assert (await client.get("/api/v1/cycle/summary", headers=h)).json()["periods"] == []
    # Another user can't touch it
    r = await client.delete(f"/api/v1/cycle/periods/{pid}", headers=h2)
    assert r.status_code == 404
