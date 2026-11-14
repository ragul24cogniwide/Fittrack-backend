"""AI assistant, step backfill and heart-rate import (Gemini is faked: no network, no cost)."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from google.genai import types
from httpx import ASGITransport, AsyncClient

from app.api.routes import ai as ai_route
from app.core.config import settings
from app.main import app, lifespan

UTC = {"X-TZ-Offset-Minutes": "0"}


@pytest.fixture
async def client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


async def _register(client):
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": f"ai_{uuid.uuid4().hex[:8]}@fittrack.io", "password": "strongPassword123!",
              "full_name": "AI User"},
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}", **UTC}


def _tool(id_, name, **args):
    return types.Part(function_call=types.FunctionCall(id=id_, name=name, args=args))


def _text(t):
    return types.Part(text=t)


def _response(parts):
    """A real SDK response object, so response.function_calls is computed by the SDK."""
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))]
    )


class FakeGemini:
    """Returns scripted responses and records every request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model, contents, config):
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        return _response(self.script.pop(0))


@pytest.fixture
def fake_gemini(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")

    def install(script):
        fake = FakeGemini(script)
        monkeypatch.setattr(ai_route, "get_ai_client", lambda: fake)
        return fake

    return install


async def test_ai_disabled_without_key(client):
    headers = await _register(client)
    res = await client.post("/api/v1/ai/chat", headers=headers,
                            json={"messages": [{"role": "user", "content": "2 eggs"}]})
    assert res.status_code == 503
    assert "GEMINI_API_KEY" in res.json()["detail"]


async def test_ai_logs_meals_water_and_weight(client, fake_gemini):
    headers = await _register(client)
    fake = fake_gemini([
        [_tool("t1", "log_meal", meal_type="Breakfast", title="2 boiled eggs",
               calories=156, protein_g=13, carbs_g=1, fats_g=11),
         _tool("t2", "log_meal", meal_type="Breakfast", title="1 slice buttered toast",
               calories=120, protein_g=3, carbs_g=15, fats_g=5),
         _tool("t3", "log_water", liters=0.5),
         _tool("t4", "log_weight", weight_kg=71.4)],
        [_text("Logged 2 eggs and toast: 276 kcal, 16 g protein.")],
    ])
    res = await client.post("/api/v1/ai/chat", headers=headers, json={"messages": [
        {"role": "user", "content": "breakfast was 2 boiled eggs and buttered toast, 2 glasses water, I weigh 71.4"},
    ]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"].startswith("Logged 2 eggs")
    assert [a["kind"] for a in body["actions"]] == ["meal_added", "meal_added", "water", "weight"]

    # Everything landed in the same tables the screens read
    nutr = (await client.get("/api/v1/nutrition/today", headers=headers)).json()
    assert nutr["calories_consumed"] == 276
    assert nutr["protein_g"] == 16 and nutr["carbs_g"] == 16 and nutr["fats_g"] == 16
    assert nutr["water_liters"] == 0.5
    assert {m["title"] for m in nutr["meals"]} == {"2 boiled eggs", "1 slice buttered toast"}
    vitals = (await client.get("/api/v1/vitals/daily", headers=headers)).json()
    assert vitals["weight_kg"] == 71.4

    # Request shape: today's numbers in the system instruction, function results sent back
    first, second = fake.requests
    assert first["model"] == settings.AI_MODEL
    assert first["config"].system_instruction.startswith(ai_route.SYSTEM_PROMPT)
    assert "Nothing logged yet today" in first["config"].system_instruction
    assert first["config"].automatic_function_calling.disable is True
    assert [c.role for c in second["contents"]] == ["user", "model", "user"]
    results = [p.function_response for p in second["contents"][-1].parts]
    assert [r.id for r in results] == ["t1", "t2", "t3", "t4"]
    assert not any("error" in r.response for r in results)


async def test_ai_correction_deletes_by_id_and_rejects_bad_input(client, fake_gemini):
    headers = await _register(client)
    meal = (await client.post("/api/v1/nutrition/meals", headers=headers, json={
        "meal_type": "Lunch", "title": "Chapati", "calories": 300, "protein_g": 8})).json()
    fake = fake_gemini([
        [_tool("t1", "delete_meal", meal_id=meal["id"]),
         _tool("t2", "log_meal", meal_type="Brunch", title="x", calories=-5,
               protein_g=0, carbs_g=0, fats_g=0)],
        [_text("Removed the chapati.")],
    ])
    res = await client.post("/api/v1/ai/chat", headers=headers,
                            json={"messages": [{"role": "user", "content": "remove the chapati"}]})
    assert res.status_code == 200, res.text
    assert [a["kind"] for a in res.json()["actions"]] == ["meal_removed"]
    # The context listed the meal id so the model could target it
    assert f"{meal['id']}: Lunch - Chapati" in fake.requests[0]["config"].system_instruction
    bad = fake.requests[1]["contents"][-1].parts[1].function_response
    assert "error" in bad.response
    nutr = (await client.get("/api/v1/nutrition/today", headers=headers)).json()
    assert nutr["calories_consumed"] == 0 and nutr["meals"] == []


async def test_ai_cannot_delete_other_users_meal(client, fake_gemini):
    owner = await _register(client)
    meal = (await client.post("/api/v1/nutrition/meals", headers=owner, json={
        "meal_type": "Lunch", "title": "Rice", "calories": 200})).json()
    intruder = await _register(client)
    fake_gemini([
        [_tool("t1", "delete_meal", meal_id=meal["id"])],
        [_text("I couldn't find that.")],
    ])
    res = await client.post("/api/v1/ai/chat", headers=intruder,
                            json={"messages": [{"role": "user", "content": "delete it"}]})
    assert res.json()["actions"] == []
    assert len((await client.get("/api/v1/nutrition/today", headers=owner)).json()["meals"]) == 1


async def test_steps_at_least_never_lowers_and_backfills(client):
    headers = await _register(client)
    today = datetime.now(timezone.utc).date()
    r = await client.patch("/api/v1/vitals/steps", headers=headers, json={"steps_at_least": 5000})
    assert r.json()["steps_count"] == 5000
    r = await client.patch("/api/v1/vitals/steps", headers=headers, json={"steps_at_least": 4200})
    assert r.json()["steps_count"] == 5000  # resend / smaller source never lowers it
    r = await client.patch("/api/v1/vitals/steps", headers=headers, json={"steps_at_least": 6100})
    assert r.json()["steps_count"] == 6100

    five_days_ago = (today - timedelta(days=5)).isoformat()
    r = await client.patch("/api/v1/vitals/steps", headers=headers,
                           json={"steps_at_least": 8000, "for_date": five_days_ago})
    assert r.status_code == 200 and r.json()["date"] == five_days_ago
    too_old = (today - timedelta(days=31)).isoformat()
    r = await client.patch("/api/v1/vitals/steps", headers=headers,
                           json={"steps_at_least": 10, "for_date": too_old})
    assert r.status_code == 400
    future = (today + timedelta(days=1)).isoformat()
    r = await client.patch("/api/v1/vitals/steps", headers=headers,
                           json={"steps_at_least": 10, "for_date": future})
    assert r.status_code == 400

    hist = (await client.get("/api/v1/history/summary?days=7", headers=headers)).json()
    by_day = {d["date"]: d["steps_count"] for d in hist["days"]}
    assert by_day[today.isoformat()] == 6100 and by_day[five_days_ago] == 8000


async def test_heart_rate_sync_imports_once(client):
    headers = await _register(client)
    today = datetime.now(timezone.utc).date().isoformat()
    readings = [
        {"date": today, "slot_label": "07:30", "bpm_value": 64},
        {"date": today, "slot_label": "08:00", "bpm_value": 128},
    ]
    r = await client.post("/api/v1/vitals/heart-rate-sync", headers=headers, json={"readings": readings})
    assert r.json() == {"imported": 2, "skipped": 0}
    r = await client.post("/api/v1/vitals/heart-rate-sync", headers=headers, json={"readings": readings})
    assert r.json() == {"imported": 0, "skipped": 2}

    zones = (await client.get("/api/v1/vitals/heart-rate-zones", headers=headers)).json()
    assert zones["readings_today"] == 2
    assert zones["latest_hr_bpm"] == 128
    assert [b["slot_label"] for b in zones["chart_bars"]] == ["07:30", "08:00"]


async def test_ai_question_without_logging(client, fake_gemini):
    headers = await _register(client)
    fake_gemini([[_text("You've had 0 g protein so far; aim for about 102 g today.")]])
    res = await client.post("/api/v1/ai/chat", headers=headers, json={"messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello! What did you eat?"},
        {"role": "user", "content": "how much protein do I need today?"},
    ]})
    assert res.status_code == 200, res.text
    assert res.json() == {"reply": "You've had 0 g protein so far; aim for about 102 g today.", "actions": []}


async def test_ai_unreachable_returns_retryable_error(client, fake_gemini):
    import httpx2

    headers = await _register(client)
    fake = fake_gemini([])

    async def down(**_kwargs):
        raise httpx2.ConnectError("connection refused")

    fake.aio.models.generate_content = down
    res = await client.post("/api/v1/ai/chat", headers=headers,
                            json={"messages": [{"role": "user", "content": "1 apple"}]})
    assert res.status_code == 502
    assert "try again" in res.json()["detail"]
