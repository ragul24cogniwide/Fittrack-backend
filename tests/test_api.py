import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app, lifespan


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_full_api_workflow():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Health Check & CORS
            res = await client.get("/health")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "healthy"
            assert data["cors_origins"] == ["*"]

            # 2. Trigger /api/v1/seed-demo (Step 5 Requirement)
            seed_res = await client.post("/api/v1/seed-demo")
            assert seed_res.status_code == 200, seed_res.text
            seed_data = seed_res.json()
            assert seed_data["status"] == "success"
            assert seed_data["user"]["full_name"] == "Jonathan Sanders"
            assert seed_data["user"]["email"] == "ragul@fittrack.io"
            assert seed_data["telemetry_sample"]["steps_count"] == 7435
            assert seed_data["telemetry_sample"]["weight_kg"] == 72.2
            assert seed_data["telemetry_sample"]["latest_hr_bpm"] == 101
            assert seed_data["telemetry_sample"]["body_composition_pct"] == 87.9
            assert seed_data["telemetry_sample"]["running_progress_pct"] == 80
            assert seed_data["telemetry_sample"]["skateboard_progress_pct"] == 50
            token = seed_data["access_token"]
            assert token is not None
            headers = {"Authorization": f"Bearer {token}"}

            # 3. Auth: Login with Demo User (Screen 1)
            login_res = await client.post(
                "/api/v1/auth/login",
                json={"email": "ragul@fittrack.io", "password": "password123"},
            )
            assert login_res.status_code == 200, login_res.text
            login_data = login_res.json()
            assert login_data["user"]["full_name"] == "Jonathan Sanders"
            user_uuid = uuid.UUID(str(login_data["user"]["id"]))
            assert user_uuid is not None

            # 4. Auth: Register a new athlete account (Screen 1)
            new_email = f"athlete_{uuid.uuid4().hex[:6]}@fittrack.io"
            reg_res = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": new_email,
                    "password": "strongPassword123!",
                    "full_name": "Marcus Aurelius",
                },
            )
            assert reg_res.status_code == 201
            assert reg_res.json()["user"]["email"] == new_email

            # 4b. Auth: Google Login OAuth (Screen 1)
            google_res = await client.post(
                "/api/v1/auth/google",
                json={
                    "email": "google_athlete@gmail.com",
                    "full_name": "Google Athlete",
                    "avatar_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100",
                },
            )
            assert google_res.status_code == 200
            assert google_res.json()["user"]["email"] == "google_athlete@gmail.com"
            assert google_res.json()["access_token"] is not None

            # 5. Auth: Onboarding Calibration (Screen 2)
            onboard_res = await client.put(
                "/api/v1/auth/onboarding",
                headers=headers,
                json={
                    "age": 24,
                    "weight_kg": 72.2,
                    "height_cm": 176.0,
                    "primary_goal": "Fat Burn",
                },
            )
            assert onboard_res.status_code == 200
            onboard_data = onboard_res.json()
            assert onboard_data["is_onboarded"] is True
            # Auto-compute target_hr_bpm: round((220 - 24) * 0.70) = 137
            assert onboard_data["target_hr_bpm"] == 137

            # 6. Dashboard: GET /today (Screen 3)
            today_res = await client.get("/api/v1/dashboard/today", headers=headers)
            assert today_res.status_code == 200
            today_data = today_res.json()
            assert today_data["user_greeting"] == "Good Morning"
            assert "Today" in today_data["date_str"]
            assert today_data["community_joined_count"] == 215
            assert today_data["workout_progress_hours"] == "10/20H"
            assert len(today_data["activity_cards"]) >= 2

            # Filter dashboard cards by ?category=Sports
            filter_res = await client.get("/api/v1/dashboard/today?category=Sports", headers=headers)
            assert filter_res.status_code == 200
            filter_data = filter_res.json()
            for card in filter_data["activity_cards"]:
                assert card["category"].lower() == "sports"

            # 7. Vitals: GET /daily (Screen 4: 7,435 steps, 72.2 kg, 101 bpm, 87.9% body comp)
            vitals_res = await client.get("/api/v1/vitals/daily", headers=headers)
            assert vitals_res.status_code == 200
            vitals_data = vitals_res.json()
            assert vitals_data["steps_count"] == 7435
            assert vitals_data["weight_kg"] == 72.2
            assert vitals_data["latest_hr_bpm"] == 101
            assert vitals_data["body_composition_pct"] == 87.9

            # 8. Vitals: PATCH /steps (Screen 4)
            patch_steps_res = await client.patch(
                "/api/v1/vitals/steps",
                headers=headers,
                json={"steps_increment": 500, "agenda_title": "Evening Jog"},
            )
            assert patch_steps_res.status_code == 200
            assert patch_steps_res.json()["steps_count"] == 7435 + 500
            assert patch_steps_res.json()["agenda_title"] == "Evening Jog"

            # 9. Vitals: GET /heart-rate-zones (Screen 5)
            hr_res = await client.get("/api/v1/vitals/heart-rate-zones", headers=headers)
            assert hr_res.status_code == 200
            hr_data = hr_res.json()
            assert len(hr_data["chart_bars"]) == 7
            assert hr_data["target_hr_bpm"] == 137
            assert hr_data["benchmarks"]["light_pct"] == "40-60%"
            assert hr_data["benchmarks"]["rem_pct"] == "15-25%"

            # 10. Nutrition: GET /today (Screen 6: 1,840 kcal, 2.5L water)
            nutr_res = await client.get("/api/v1/nutrition/today", headers=headers)
            assert nutr_res.status_code == 200
            nutr_data = nutr_res.json()
            assert nutr_data["calories_consumed"] >= 1840
            assert nutr_data["water_liters"] == 2.5
            assert nutr_data["metabolic_score_pct"] == 92
            assert len(nutr_data["meals"]) >= 4

            # 11. Nutrition: POST /hydration (+0.25L increment) (Screen 6)
            hydration_res = await client.post("/api/v1/nutrition/hydration", headers=headers)
            assert hydration_res.status_code == 200
            assert hydration_res.json()["water_liters"] == 2.75

            # 12. Nutrition: POST /meals (Screen 6)
            meal_res = await client.post(
                "/api/v1/nutrition/meals",
                headers=headers,
                json={
                    "meal_type": "Snacks",
                    "title": "Avocado Protein Toast",
                    "calories": 280,
                    "protein_g": 16,
                },
            )
            assert meal_res.status_code == 201
            meal_id = meal_res.json()["id"]

            # 13. Workouts: POST /start (Screen 7)
            start_res = await client.post(
                "/api/v1/workouts/start",
                headers=headers,
                json={
                    "title": "Running",
                    "category": "Sports",
                    "target_duration_seconds": 2850,
                },
            )
            assert start_res.status_code in (200, 201)
            workout = start_res.json()
            workout_id = workout["id"]
            assert workout["status"] == "in_progress"

            # 14. Workouts: PATCH /{workout_id}/tick (Screen 7 live heartbeat)
            tick_res = await client.patch(
                f"/api/v1/workouts/{workout_id}/tick",
                headers=headers,
                json={
                    "duration_seconds": 720,
                    "distance_km": 1.8,
                    "live_bpm": 146,
                    "progress_pct": 35,
                    "calories_burned": 150,
                    "pace_str": "5'10\" /km",
                },
            )
            assert tick_res.status_code == 200
            assert tick_res.json()["duration_seconds"] == 720
            assert tick_res.json()["pace_str"] == "5'10\" /km"

            # 15. Workouts: POST /{workout_id}/complete (Screen 7 completion)
            complete_res = await client.post(
                f"/api/v1/workouts/{workout_id}/complete",
                headers=headers,
            )
            assert complete_res.status_code == 200
            assert complete_res.json()["status"] == "completed"

            # 16. Delete added meal
            del_meal_res = await client.delete(
                f"/api/v1/nutrition/meals/{meal_id}",
                headers=headers,
            )
            assert del_meal_res.status_code == 204
