"""Sleep tracking: sources, scoring, summary, history and the AI tool."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes.sleep import night_score
from app.main import app, lifespan

UTC = {"X-TZ-Offset-Minutes": "0"}


@pytest.fixture
async def client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def _register(client):
    res = await client.post("/api/v1/auth/register", json={
        "email": f"sleep_{uuid.uuid4().hex[:8]}@fittrack.io",
        "password": "strongPassword123!", "full_name": "Sleepy"})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}", **UTC}


def _night(days_ago, bed, wake):
    """Local ISO times for the night that ended `days_ago` days ago."""
    wake_day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    bh, bm = map(int, bed.split(":"))
    wh, wm = map(int, wake.split(":"))
    end = datetime(wake_day.year, wake_day.month, wake_day.day, wh, wm)
    start_day = wake_day if (bh, bm) < (wh, wm) else wake_day - timedelta(days=1)
    start = datetime(start_day.year, start_day.month, start_day.day, bh, bm)
    return start.isoformat(), end.isoformat(), wake_day.isoformat()


def test_night_score():
    assert night_score(8 * 60, None, None) == 100
    assert night_score(6 * 60, None, None) == 80  # 1 h short
    assert night_score(5 * 60, None, None) == 60
    assert night_score(10 * 60, None, None) == 90
    assert night_score(8 * 60, 60, None) == 92  # 40 min extra awake -> -8
    assert night_score(8 * 60, None, 1) == 76  # 70% of 100 + 30% of 20
    assert night_score(0, None, None) == 0


async def test_better_sources_win_and_rating_is_kept(client):
    h = await _register(client)
    start, end, day = _night(1, "23:40", "06:55")
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": start, "end": end, "source": "phone"})
    assert r.status_code == 200, r.text
    assert r.json()["asleep_min"] == 435 and r.json()["date"] == day and not r.json()["confirmed"]

    # Morning check: "yes, that's right", felt rested
    r = await client.post(f"/api/v1/sleep/sessions/{day}/confirm", headers=h, json={"rating": 4})
    assert r.json()["confirmed"] and r.json()["rating"] == 4

    # A watch reports the same night with stages: it replaces the phone's guess, keeps the rating
    s2, e2, _ = _night(1, "23:50", "06:50")
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={
        "start": s2, "end": e2, "source": "health_connect",
        "stages": {"awake_min": 30, "light_min": 220, "deep_min": 90, "rem_min": 80}})
    body = r.json()
    assert body["source"] == "health_connect" and body["asleep_min"] == 390
    assert body["deep_min"] == 90 and body["rating"] == 4 and body["confirmed"]

    # A late phone estimate can't overwrite the watch
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": start, "end": end, "source": "phone"})
    assert r.json()["source"] == "health_connect" and r.json()["asleep_min"] == 390

    # The user's own correction beats everything
    s3, e3, _ = _night(1, "00:15", "07:00")
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": s3, "end": e3, "source": "manual"})
    assert r.json()["source"] == "manual" and r.json()["asleep_min"] == 405
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": s2, "end": e2, "source": "health_connect"})
    assert r.json()["source"] == "manual"


async def test_invalid_nights_are_rejected(client):
    h = await _register(client)
    start, end, _ = _night(0, "06:00", "06:10")
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": start, "end": end})
    assert r.status_code == 400  # 10 minutes
    start, end, _ = _night(-1, "23:00", "07:00")
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": start, "end": end})
    assert r.status_code == 400  # ends tomorrow
    start, end, _ = _night(40, "23:00", "07:00")
    r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": start, "end": end})
    assert r.status_code == 400  # too old
    r = await client.post("/api/v1/sleep/sessions/2026-01-01/confirm", headers=h, json={})
    assert r.status_code == 404


async def test_summary_history_and_delete(client):
    h = await _register(client)
    nights = [(0, "23:30", "07:00"), (1, "00:30", "06:30"), (2, "23:00", "06:00"), (3, "01:00", "06:00")]
    for days_ago, bed, wake in nights:
        start, end, _ = _night(days_ago, bed, wake)
        r = await client.put("/api/v1/sleep/sessions", headers=h, json={"start": start, "end": end, "source": "manual"})
        assert r.status_code == 200, r.text

    s = (await client.get("/api/v1/sleep/summary?days=7", headers=h)).json()
    assert s["last_night"]["asleep_min"] == 450
    assert [n["asleep_min"] for n in s["nights"]][-4:] == [300, 420, 360, 450]
    assert s["nights_logged"] == 4
    assert s["avg_asleep_min"] == 382  # (450+360+420+300)/4 = 382.5, rounded to even
    assert s["sleep_debt_min"] == 30 + 120 + 60 + 180
    # Bedtimes 23:00-01:00 straddle midnight: average ~00:00, not noon
    assert s["avg_bedtime"] == "00:00"
    assert 40 <= s["bedtime_variation_min"] <= 50
    assert s["tip"]

    hist = (await client.get("/api/v1/history/summary?days=7", headers=h)).json()
    assert hist["days"][-1]["sleep_minutes"] == 450
    assert hist["totals"]["avg_sleep_minutes"] == 382 and hist["totals"]["nights_logged"] == 4
    today = hist["days"][-1]["date"]
    detail = (await client.get(f"/api/v1/history/day/{today}", headers=h)).json()
    assert detail["sleep"]["asleep_min"] == 450

    r = await client.delete(f"/api/v1/sleep/sessions/{today}", headers=h)
    assert r.status_code == 204
    s = (await client.get("/api/v1/sleep/summary?days=7", headers=h)).json()
    assert s["last_night"] is None and s["nights_logged"] == 3


async def test_other_users_sleep_is_private(client):
    owner = await _register(client)
    start, end, day = _night(0, "23:00", "07:00")
    await client.put("/api/v1/sleep/sessions", headers=owner, json={"start": start, "end": end})
    other = await _register(client)
    assert (await client.get("/api/v1/sleep/summary", headers=other)).json()["nights_logged"] == 0
    await client.delete(f"/api/v1/sleep/sessions/{day}", headers=other)
    assert (await client.get("/api/v1/sleep/summary", headers=owner)).json()["nights_logged"] == 1
