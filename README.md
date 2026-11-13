# Movements+ & FitTrack FastAPI Backend

A production-ready, modular FastAPI backend integrated with **NeonDB (Serverless PostgreSQL)** tailored specifically for the Movements+ / FitTrack 7-screen React Native application.

---

## 1. Tech Stack & Architecture

- **Runtime:** Python 3.11+ / 3.12+
- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Async ASGI)
- **Database ORM:** [SQLAlchemy 2.0](https://docs.sqlalchemy.org/) (Async with `Mapped` & `mapped_column`)
- **PostgreSQL Driver:** [asyncpg](https://magicstack.github.io/asyncpg/)
- **Serverless Database:** [NeonDB](https://neon.tech/) with connection pooling (`pool_pre_ping=True`, disabled statement cache for PgBouncer)
- **Validation:** [Pydantic v2](https://docs.pydantic.dev/) (`BaseModel`, `ConfigDict(from_attributes=True)`)
- **Authentication:** JWT (`python-jose`) + `passlib[bcrypt]`

---

## 2. Directory Layout

```
backend/
├── app/
│   ├── main.py                # FastAPI app entry point, CORS, table lifespan, demo seeding
│   ├── core/
│   │   ├── config.py          # Pydantic BaseSettings (.env loader, auto-normalizes Neon URLs)
│   │   └── security.py        # Bcrypt password hashing & JWT token encode/decode
│   ├── db/
│   │   ├── session.py         # NeonDB AsyncEngine & AsyncSession with pool_pre_ping
│   │   └── base.py            # DeclarativeBase for SQLAlchemy models
│   ├── models/                # SQLAlchemy ORM Database Tables
│   │   ├── user.py            # Users & Biometrics (Screen 1 & 2)
│   │   ├── activity.py        # Workouts, Steps, Body Composition (Screens 3, 4, 7)
│   │   ├── heart_rate.py      # Heart Rate Logs & Sleep/Zone Benchmarks (Screens 4 & 5)
│   │   └── nutrition.py       # Daily Calories, Macros, Meals, Hydration (Screen 6)
│   ├── schemas/               # Pydantic v2 Request/Response Schemas
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── activity.py
│   │   ├── heart_rate.py
│   │   └── nutrition.py
│   └── api/
│       ├── deps.py            # get_db and get_current_user dependencies
│       └── routes/
│           ├── auth.py        # Screen 1 & 2 endpoints (Register, Login, Onboarding)
│           ├── dashboard.py   # Screen 3 ("Today, Movements+") endpoints
│           ├── vitals.py      # Screen 4 ("Daily Activities") & Screen 5 ("Heart Rate Zone")
│           ├── nutrition.py   # Screen 6 ("Nutrients Details") endpoints
│           └── workouts.py    # Screen 7 ("Active Workout Session") endpoints
├── tests/
│   └── test_api.py            # End-to-end integration test suite
├── requirements.txt
├── pytest.ini
├── .env.example
└── README.md
```

---

## 3. Screen to Endpoint Mapping

| React Native Screen | Endpoint | Method | Description |
|---|---|---|---|
| **Screen 1: Login** | `/api/v1/auth/login` | `POST` | Authenticate user, returns JWT + Profile |
| **Screen 1: Register** | `/api/v1/auth/register` | `POST` | Register account |
| **Screen 2: Onboarding** | `/api/v1/auth/onboarding` | `PUT` | Calibrates Age, Weight, Height, Goal, & Target Heart Rate (`round((220 - age) * 0.70)`) |
| **Screen 3: Home Dashboard** | `/api/v1/dashboard/overview` | `GET` | Aggregated widgets, progress ring, active cards, and nutrients bar |
| **Screen 4: Daily Activities** | `/api/v1/vitals/daily` | `GET`, `PUT` | Steps (7,435), 5.8 km, scalloped body composition (54.2% muscle) |
| **Screen 5: Heart Rate Zone** | `/api/v1/vitals/heart-rate-zone` | `GET` | 7 vertical pill bars, active peak bar (134 bpm), and benchmark ranges |
| **Screen 5: Vitals Log** | `/api/v1/vitals/heart-rate-log` | `POST` | Log discrete heart rate measurement |
| **Screen 6: Nutrients** | `/api/v1/nutrition/daily` | `GET` | 1,840 / 2,400 kcal, macros, and meal logs |
| **Screen 6: Hydration** | `/api/v1/nutrition/water` | `POST` | Log water in increments (+0.25L, +0.50L) |
| **Screen 6: Meal Log** | `/api/v1/nutrition/meals` | `POST`, `DELETE` | Log or remove meal |
| **Screen 7: Active Workout** | `/api/v1/workouts/start` | `POST` | Start Running/Skateboard workout |
| **Screen 7: Live Heartbeat** | `/api/v1/workouts/{id}/update` | `PUT` | Update duration, distance, calories |
| **Screen 7: Finish Workout** | `/api/v1/workouts/{id}/finish` | `POST` | Complete session and sync with Daily Activities |

---

## 4. Setup & Running

### 1. Environment Configuration
Copy `.env.example` to `.env` and fill in real values (`.env` is gitignored; never commit secrets):
```bash
cp .env.example .env
```

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | Yes (hosted) | NeonDB connection string. `postgresql://...?sslmode=require&channel_binding=require` works as copied from Neon. |
| `JWT_SECRET` | Yes (hosted) | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | For Google sign-in | Google Cloud Console -> Credentials -> OAuth client ID -> **Web application** |
| `PUBLIC_BASE_URL` | For Google sign-in | e.g. `https://fittrack-backend-nqkx.onrender.com`. Add `{PUBLIC_BASE_URL}/api/v1/auth/google/callback` as an Authorized redirect URI on the Google client. |

On Render (detected via `RENDER=true`) or with `ENVIRONMENT=production`, the server **refuses to start** without `DATABASE_URL` and `JWT_SECRET`, instead of silently falling back to a throwaway SQLite file.

### 2. Install & Run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Tables are created automatically on startup (`Base.metadata.create_all`, idempotent). `init_neondb.sql` contains the same schema for manual setup.

### 3. Verify
- **Health:** `GET /health` reports which database is in use, whether it is reachable, and whether Google sign-in is configured.
- **Docs:** `/api/v1/docs`

### 4. Tests
```bash
pytest                                   # throwaway SQLite
TEST_DATABASE_URL=postgresql://... pytest  # a disposable Postgres database (never your real one)
```

---

## 5. Data Notes
- New accounts start with empty data; every number on every screen comes from the database.
- "Today" follows the phone's calendar day via the `X-TZ-Offset-Minutes` header.
- Steps come from the phone's hardware step counter (`PATCH /vitals/steps` increments).
- Heart rate is logged manually (watch reading / pulse check) via `POST /vitals/heart-rate-log`.
