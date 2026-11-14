"""
AI assistant: the user types what they ate / drank / weighed in plain words
("2 idlis with sambar and a filter coffee") and Google Gemini logs it with the
same helpers the Nutrients and Daily Activities screens use.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.daily import client_today, get_or_create_daily
from app.api.deps import get_current_user, get_db
from app.api.routes.nutrition import (
    MEAL_TYPES,
    PROTEIN_G_PER_KG,
    add_meal,
    add_water,
    list_meals,
    remove_meal,
)
from app.api.routes.vitals import save_daily_vitals
from app.core.config import settings
from app.models.nutrition import NutritionLog
from app.models.user import User
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

try:  # google-genai talks over httpx2; older releases used httpx
    import httpx2

    _NETWORK_ERRORS: tuple = (httpx.HTTPError, httpx2.HTTPError)
except ImportError:  # pragma: no cover
    _NETWORK_ERRORS = (httpx.HTTPError,)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Assistant"])

MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """You are the nutrition assistant inside FitTrack, a fitness app. The user tells you in everyday language what they ate, drank or weighed, and you record it with your tools so their calories, protein, carbs, fats, water and weight stay up to date.

How to log:
- Food or drink with calories: call log_meal once per distinct item (e.g. "2 boiled eggs" and "1 slice buttered toast" are two calls), so the user can delete items individually. Estimate realistic calories and macros (grams) for the stated portion; when no portion is given, assume a typical single serving. Indian, regional and home-cooked dishes are common; estimate them sensibly.
- meal_type: use the one the user says. Otherwise pick from their local time: before 11:00 Breakfast, 11:00-16:00 Lunch, 16:00-18:30 Snacks, after 18:30 Dinner; small items between meals are Snacks.
- Plain water: call log_water with the amount in liters (a glass is about 0.25 L). Tea, coffee, juice and milk are logged with log_meal, not as water.
- A body weight ("I weigh 72 kg", "weight 158 lb"): call log_weight in kilograms.
- Corrections ("remove the toast", "that was 3 eggs, not 2"): use the meal ids from today's context; delete the wrong entry and log the corrected one.
- Questions ("how much protein today?", "what should I eat for dinner?"): answer from today's context without logging anything.
- If a message is too vague to estimate (e.g. "I ate something"), ask one short question instead of guessing.

After logging, reply in one or two short sentences: what you logged with its calories and protein, then today's new totals against the goals. No markdown headings or tables; this is a small chat bubble on a phone. Only discuss food, hydration, weight, exercise and general wellbeing; for medical concerns suggest seeing a doctor."""

_INT = {"type": "integer"}


def _fn(name: str, description: str, properties: dict) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters_json_schema={
            "type": "object",
            "properties": properties,
            "required": list(properties),
        },
    )


FUNCTIONS: List[types.FunctionDeclaration] = [
    _fn(
        "log_meal",
        "Adds one food or drink entry to today's nutrition log. Calories in kcal, macros in grams, for the portion eaten.",
        {
            "meal_type": {"type": "string", "enum": list(MEAL_TYPES)},
            "title": {"type": "string", "description": "Short name with portion, e.g. '2 boiled eggs'"},
            "calories": _INT,
            "protein_g": _INT,
            "carbs_g": _INT,
            "fats_g": _INT,
        },
    ),
    _fn(
        "delete_meal",
        "Removes one of today's logged entries by its id (ids are listed in today's context).",
        {"meal_id": _INT},
    ),
    _fn(
        "log_water",
        "Adds plain water drunk today, in liters. Use a negative amount to correct an over-count.",
        {"liters": {"type": "number"}},
    ),
    _fn(
        "log_weight",
        "Records today's body weight in kilograms (convert from pounds if needed).",
        {"weight_kg": {"type": "number"}},
    ),
]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: List[ChatTurn] = Field(..., min_length=1, max_length=20)


class ChatAction(BaseModel):
    kind: Literal["meal_added", "meal_removed", "water", "weight"]
    label: str
    meal_id: Optional[int] = None
    meal_type: Optional[str] = None
    calories: int = 0
    protein_g: int = 0
    carbs_g: int = 0
    fats_g: int = 0
    amount: Optional[float] = None


class ChatResponse(BaseModel):
    reply: str
    actions: List[ChatAction] = []


_client: Optional[genai.Client] = None


def get_ai_client() -> genai.Client:
    """Lazily created so the app starts fine without a key; tests override this."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _local_now(offset_minutes: Optional[int]) -> datetime:
    now = datetime.now(timezone.utc)
    if offset_minutes is not None and -840 <= offset_minutes <= 840:
        now -= timedelta(minutes=offset_minutes)
    return now


async def _today_context(db: AsyncSession, user: User, today: date, local_now: datetime) -> str:
    nutr = await get_or_create_daily(db, NutritionLog, user, today)
    meals = await list_meals(db, nutr)
    protein_goal = round(user.weight_kg * PROTEIN_G_PER_KG)
    lines = [
        f"Today's context ({local_now:%A %d %B %Y}, local time {local_now:%H:%M}):",
        f"User: {user.full_name or 'User'}, {user.age} y, {user.weight_kg:g} kg, {user.height_cm:g} cm, goal: {user.primary_goal}.",
        f"Eaten so far: {nutr.calories_consumed} / {nutr.calories_goal} kcal, protein {nutr.protein_g} / {protein_goal} g, "
        f"carbs {nutr.carbs_g} g, fats {nutr.fats_g} g, water {nutr.water_liters:g} / {nutr.water_goal_liters:g} L.",
    ]
    if meals:
        lines.append("Logged today (id: type - title - kcal/protein):")
        for m in reversed(meals):  # oldest first
            lines.append(f"  {m.id}: {m.meal_type} - {m.title} - {m.calories} kcal / {m.protein_g} g")
    else:
        lines.append("Nothing logged yet today.")
    return "\n".join(lines)


async def _run_tool(
    name: str, args: dict, db: AsyncSession, user: User, today: date, actions: List[ChatAction]
) -> str:
    """Executes one function call; returns the text result for the model. Raises ValueError on bad input."""
    if name == "log_meal":
        meal_type = args.get("meal_type")
        if meal_type not in MEAL_TYPES:
            raise ValueError(f"meal_type must be one of {', '.join(MEAL_TYPES)}")
        title = str(args.get("title", "")).strip()
        if len(title) < 2:
            raise ValueError("title is required")
        nums = {}
        for key, upper in (("calories", 10000), ("protein_g", 1000), ("carbs_g", 2000), ("fats_g", 1000)):
            value = int(args.get(key, 0))
            if not 0 <= value <= upper:
                raise ValueError(f"{key} must be between 0 and {upper}")
            nums[key] = value
        meal = await add_meal(db, user, today, meal_type=meal_type, title=title, **nums)
        actions.append(ChatAction(kind="meal_added", label=meal.title, meal_id=meal.id, meal_type=meal_type, **nums))
        return f"Logged meal id {meal.id}: {meal.title} ({nums['calories']} kcal)."

    if name == "delete_meal":
        meal = await remove_meal(db, user, int(args.get("meal_id", 0)))
        if meal is None:
            raise ValueError("No meal with that id for this user")
        actions.append(ChatAction(
            kind="meal_removed", label=meal.title, meal_id=meal.id, meal_type=meal.meal_type,
            calories=meal.calories, protein_g=meal.protein_g, carbs_g=meal.carbs_g, fats_g=meal.fats_g,
        ))
        return f"Removed {meal.title}."

    if name == "log_water":
        liters = float(args.get("liters", 0))
        if not -3 <= liters <= 3 or liters == 0:
            raise ValueError("liters must be between -3 and 3 and not zero")
        nutr = await add_water(db, user, today, liters)
        actions.append(ChatAction(kind="water", label=f"{liters:+g} L water", amount=liters))
        return f"Water today is now {nutr.water_liters:g} L."

    if name == "log_weight":
        kg = round(float(args.get("weight_kg", 0)), 1)
        if not 25 <= kg <= 400:
            raise ValueError("weight_kg must be between 25 and 400")
        await save_daily_vitals(db, user, today, weight_kg=kg)
        actions.append(ChatAction(kind="weight", label=f"Weight {kg:g} kg", amount=kg))
        return f"Weight recorded: {kg:g} kg."

    raise ValueError(f"Unknown tool {name}")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    today: date = Depends(client_today),
    x_tz_offset_minutes: Optional[int] = Header(None),
):
    """One chat turn: Gemini reads the conversation, logs what the user reported and replies."""
    if not settings.ai_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI assistant is not set up yet. Add GEMINI_API_KEY to the backend environment.",
        )
    if payload.messages[-1].role != "user":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The last message must be from the user")

    # Today's numbers (and meal ids for corrections) go in the system instruction
    context = await _today_context(db, current_user, today, _local_now(x_tz_offset_minutes))
    turns = [m for m in payload.messages]
    while turns and turns[0].role != "user":
        turns.pop(0)
    contents: List[Any] = [
        types.Content(role="user" if m.role == "user" else "model", parts=[types.Part(text=m.content)])
        for m in turns
    ]
    config = types.GenerateContentConfig(
        system_instruction=f"{SYSTEM_PROMPT}\n\n{context}",
        tools=[types.Tool(function_declarations=FUNCTIONS)],
        # We run the functions ourselves (they write to the user's log)
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    client = get_ai_client()
    actions: List[ChatAction] = []
    reply = ""
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = await client.aio.models.generate_content(
                model=settings.AI_MODEL, contents=contents, config=config
            )
            candidate = response.candidates[0] if response.candidates else None
            if candidate is None or candidate.content is None:
                # Blocked by a safety filter or empty answer
                reply = reply or "Sorry, I can't help with that. I can log meals, water and weight for you."
                break
            parts = candidate.content.parts or []
            text = "".join(p.text for p in parts if p.text and not p.thought).strip()
            reply = text or reply
            calls = response.function_calls or []
            if not calls:
                break

            # Keep the model's turn exactly as returned (it carries thought signatures)
            contents.append(candidate.content)
            results = []
            for call in calls:
                try:
                    result = {"result": await _run_tool(
                        call.name, dict(call.args or {}), db, current_user, today, actions
                    )}
                except (ValueError, TypeError) as exc:
                    result = {"error": str(exc)}
                results.append(types.Part(function_response=types.FunctionResponse(
                    id=call.id, name=call.name, response=result,
                )))
            contents.append(types.Content(role="user", parts=results))
    except genai_errors.APIError as exc:
        logger.exception("Gemini API call failed")
        if exc.code in (401, 403) or (exc.code == 400 and "API key" in str(exc)):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="The AI assistant's API key is invalid. Check GEMINI_API_KEY.")
        if actions:  # some items were already saved; tell the user rather than failing
            reply = reply or "I logged part of that but lost connection. Check your Nutrients list."
        elif exc.code == 429:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="The AI assistant is busy. Please try again in a minute.")
        else:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Could not reach the AI assistant. Please try again.")
    except _NETWORK_ERRORS:
        logger.exception("Gemini API unreachable")
        if not actions:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Could not reach the AI assistant. Please try again.")
        reply = reply or "I logged part of that but lost connection. Check your Nutrients list."

    if not reply:
        reply = "Done." if actions else "Sorry, I didn't catch that. Tell me what you ate or drank."
    return ChatResponse(reply=reply, actions=actions)
