"""Google sign-in fills in the gender from the Google account when shared."""
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.core.security import create_access_token
from app.main import app, lifespan


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-secret")
    async with lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            yield c


def _fake_google(monkeypatch, email, people_status=200, genders=None):
    """Stands in for Google's token endpoint and People API."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            id_token = jwt.encode(
                {"aud": settings.GOOGLE_CLIENT_ID, "iss": "https://accounts.google.com",
                 "email": email, "email_verified": True, "name": "Gina"},
                "not-checked", algorithm="HS256")
            return httpx.Response(200, json={"id_token": id_token, "access_token": "at-123"})
        if request.url.host == "people.googleapis.com":
            seen["auth"] = request.headers.get("authorization")
            seen["fields"] = request.url.params.get("personFields")
            return httpx.Response(people_status, json={"genders": genders or []})
        return httpx.Response(404)

    monkeypatch.setattr(auth_routes, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


async def _sign_in(client):
    state = create_access_token(subject="google_oauth", extra_claims={"purpose": "google_oauth", "app_state": "s"})
    res = await client.get("/api/v1/auth/google/callback", params={"code": "c", "state": state})
    assert res.status_code == 200
    link = res.text.split('url=')[1].split('"')[0].replace("&amp;", "&")
    token = parse_qs(urlparse(link).query)["token"][0]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return me.json(), token


async def test_start_asks_google_for_gender(client):
    res = await client.get("/api/v1/auth/google/start", follow_redirects=False)
    scope = parse_qs(urlparse(res.headers["location"]).query)["scope"][0]
    assert "https://www.googleapis.com/auth/user.gender.read" in scope.split()


async def test_gender_comes_from_google(client, monkeypatch):
    seen = _fake_google(monkeypatch, f"g_{uuid.uuid4().hex[:6]}@gmail.com",
                        genders=[{"value": "female", "formattedValue": "Female"}])
    me, _ = await _sign_in(client)
    assert me["gender"] == "female"
    assert seen == {"auth": "Bearer at-123", "fields": "genders"}


async def test_not_shared_or_other_leaves_it_for_the_app(client, monkeypatch):
    # Permission unticked on Google's screen -> People API refuses
    _fake_google(monkeypatch, f"g_{uuid.uuid4().hex[:6]}@gmail.com", people_status=403)
    me, _ = await _sign_in(client)
    assert me["gender"] is None
    # A custom / unspecified value -> the app asks instead
    _fake_google(monkeypatch, f"g_{uuid.uuid4().hex[:6]}@gmail.com", genders=[{"value": "unspecified"}])
    me, _ = await _sign_in(client)
    assert me["gender"] is None


async def test_choice_made_in_the_app_is_kept(client, monkeypatch):
    email = f"g_{uuid.uuid4().hex[:6]}@gmail.com"
    _fake_google(monkeypatch, email, people_status=403)
    _, token = await _sign_in(client)
    await client.patch("/api/v1/auth/profile", headers={"Authorization": f"Bearer {token}"}, json={"gender": "male"})
    # Next sign-in Google says female: the user's own choice wins
    _fake_google(monkeypatch, email, genders=[{"value": "female"}])
    me, _ = await _sign_in(client)
    assert me["gender"] == "male"


async def test_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_REQUEST_GENDER", False)
    res = await client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert "user.gender.read" not in res.headers["location"]
