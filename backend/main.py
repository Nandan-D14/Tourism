"""FastAPI wrapper for the Tourist Place Finder ADK application."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"
load_dotenv(BASE_DIR / ".env", override=True)

from tourist_agent import root_agent
from tourist_agent.agent import current_timestamp
from tourist_agent.sub_agents.itinerary_builder import itinerary_builder_agent
from tourist_agent.sub_agents.place_finder import place_finder_agent
from tourist_agent.tools.itinerary_tools import add_travel_tips, create_time_slots
from tourist_agent.tools.place_tools import format_place_details, search_places

APP_NAME = "tourist_agent"
AGENT_NAME = "tourist_place_finder"
DEFAULT_USER_ID = "hackathon-user"
PLACE_FINDER_AGENT_NAME = "place_finder_agent"
ITINERARY_AGENT_NAME = "itinerary_builder_agent"

logger = logging.getLogger(__name__)


class PlaceRequest(BaseModel):
    """Request body for the tourist place finder endpoint."""

    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=1, description="Destination city name.")
    interest: str = Field(min_length=1, description="Traveler interest or theme.")
    budget: str = Field(default="Mid-range", description="Travel budget (Budget, Mid-range, Luxury).")
    duration_days: int = Field(default=1, ge=1, le=10, description="Number of days (1-10).")
    group_type: str = Field(default="solo", description="Group type (solo, family, couple, friends).")
    dates: str = Field(default="", description="Travel dates.")
    diet: str = Field(default="Any", description="Dietary preferences.")
    pace: str = Field(default="Medium", description="Pace of travel (Relaxed, Medium, Packed).")


class PlaceCard(BaseModel):
    """One tourist place returned to the frontend."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    best_time: str
    entry_fee: str
    tips: str
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    images: list[str] | None = None
    address: str | None = None
    nearby_places: list[str] = Field(default_factory=list)
    nearby_restaurants: list[str] = Field(default_factory=list)


class ItinerarySlot(BaseModel):
    """One slot in the day itinerary."""

    model_config = ConfigDict(extra="forbid")

    time: str
    place: str
    activity: str
    travel_note: str


class DayItinerary(BaseModel):
    """A full day of an itinerary."""
    
    model_config = ConfigDict(extra="forbid")

    day: int
    morning: ItinerarySlot
    midmorning: ItinerarySlot
    afternoon: ItinerarySlot
    evening: ItinerarySlot


class PlaceResponse(BaseModel):
    """Final API response returned by the Tourist Place Finder app."""

    model_config = ConfigDict(extra="forbid")

    city: str
    interest: str
    places: list[PlaceCard]
    itinerary: list[DayItinerary] | dict[str, ItinerarySlot]
    travel_tips: list[str] = Field(min_length=3, max_length=10)
    weather_context: str | None = None
    vlog_links: list[str] | None = None
    generated_at: str


def _load_environment() -> None:
    """Loads the backend environment file for local development."""

    load_dotenv(BASE_DIR / ".env", override=True)


def _credentials_configured() -> bool:
    """Returns whether backend model credentials are available."""

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    return bool(api_key) and api_key.lower() not in {
        "your_openrouter_api_key_here",
        "changeme",
        "replace_me",
    }


def _strip_markdown_code_fences(payload: str) -> str:
    """Removes optional Markdown code fences from a model response."""

    stripped = payload.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_text_payload(event) -> str:
    """Collects the last text fragment from an ADK event."""

    if not event.content or not event.content.parts:
        return ""
    text_chunks = [part.text for part in event.content.parts if getattr(part, "text", None)]
    return text_chunks[-1] if text_chunks else ""


def _extract_function_payload(event) -> str:
    """Collects structured function-response payloads from an ADK event."""

    if not event.content or not event.content.parts:
        return ""

    function_chunks: list[str] = []
    for part in event.content.parts:
        function_response = getattr(part, "function_response", None)
        if not function_response or not getattr(function_response, "response", None):
            continue
        result = function_response.response.get("result")
        if isinstance(result, str):
            function_chunks.append(result)
        elif result is not None:
            function_chunks.append(json.dumps(result))

    return function_chunks[-1] if function_chunks else ""


def _map_agent_exception(exc: Exception) -> HTTPException:
    """Maps common upstream model and ADK runtime failures to useful HTTP responses."""

    message = str(exc)
    message_lower = message.lower()

    if any(
        pattern in message_lower
        for pattern in ("429", "resource_exhausted", "too many requests", "rate limit")
    ):
        return HTTPException(
            status_code=429,
            detail="Gemini is temporarily rate limited for the current backend key/model. Retry shortly.",
        )
    if any(pattern in message_lower for pattern in ("503", "unavailable", "high demand")):
        return HTTPException(
            status_code=503,
            detail="Gemini is temporarily under high demand. Retry shortly.",
        )
    if any(
        pattern in message_lower
        for pattern in ("401", "unauthorized", "authentication", "invalid api key")
    ):
        return HTTPException(
            status_code=401,
            detail="Gemini access is unauthorized. Check the configured backend API key.",
        )
    if any(
        pattern in message_lower
        for pattern in ("402", "spend limit exceeded", "usd spending limit")
    ):
        return HTTPException(
            status_code=402,
            detail="OpenRouter key spend limit exceeded for the selected provider/model. Top up credits, change API key, or switch model.",
        )
    if any(
        pattern in message_lower
        for pattern in ("badrequesterror", "provider returned error", "openrouterexception")
    ):
        return HTTPException(
            status_code=502,
            detail="Gemini returned an upstream model error before producing a valid result.",
        )
    return HTTPException(
        status_code=500,
        detail="Agent execution failed before Gemini returned a valid result.",
    )


def _build_tool_fallback_payload(city: str, interest: str) -> dict[str, object]:
    """Builds the final response shape directly from the FunctionTools as a safety net."""

    # Keep fallback independent from upstream model availability.
    # This guarantees the app can still respond when provider calls fail.
    place_names = [
        f"{city} Old Town Walk",
        f"{city} Riverside Promenade",
        f"{city} Heritage Museum",
        f"{city} Central Food Street",
        f"{city} Sunset Viewpoint",
    ]

    place_details = format_place_details(city, place_names)
    itinerary = create_time_slots(place_names, city)
    travel_tips = add_travel_tips(city, interest)
    return {
        "city": city,
        "interest": interest,
        "places": place_details.get("places"),
        "itinerary": itinerary.get("itinerary") if isinstance(itinerary, dict) else itinerary,
        "travel_tips": travel_tips.get("tips") if isinstance(travel_tips, dict) else travel_tips,
        "generated_at": current_timestamp()["generated_at"],
    }


def _normalize_itinerary_shape(itinerary_value: object) -> object:
    """Normalizes variant itinerary payloads from tools/agents into API response shape."""

    if isinstance(itinerary_value, dict) and "itinerary" in itinerary_value:
        return itinerary_value.get("itinerary")
    return itinerary_value


def _normalize_tips_shape(tips_value: object) -> list[str]:
    """Normalizes variant travel tips payloads into a list of strings."""

    if isinstance(tips_value, dict):
        tips_value = tips_value.get("tips")

    if isinstance(tips_value, list):
        return [str(tip) for tip in tips_value if tip is not None]

    return []


async def _run_agent_json(
    *,
    runner: Runner,
    session_service: InMemorySessionService,
    agent_name: str,
    payload: dict[str, object],
    retries: int = 1,
) -> dict[str, object]:
    """Runs one ADK agent and returns its final JSON payload."""

    last_error: HTTPException | None = None
    message_text = json.dumps(payload)

    for attempt in range(retries):
        session_id = f"{agent_name}-{uuid4()}"
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=DEFAULT_USER_ID,
            session_id=session_id,
        )

        final_response_text = ""
        fallback_final_text = ""
        structured_payload = ""
        events = runner.run_async(
            user_id=DEFAULT_USER_ID,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part.from_text(text=message_text)],
            ),
        )

        try:
            async with asyncio.timeout(25):
                async for event in events:
                    function_payload = _extract_function_payload(event)
                    if function_payload:
                        structured_payload = function_payload

                    text_payload = _extract_text_payload(event)
                    if text_payload:
                        fallback_final_text = text_payload
                        if event.author == agent_name and event.is_final_response():
                            final_response_text = text_payload
        except TimeoutError as exc:
            mapped_error = HTTPException(
                status_code=504,
                detail="Model request timed out. Falling back to local itinerary generation.",
            )
            if attempt < retries - 1:
                await asyncio.sleep(1)
                last_error = mapped_error
                continue
            raise mapped_error from exc
        except Exception as exc:
            mapped_error = _map_agent_exception(exc)
            if mapped_error.status_code == 429 and attempt < retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                last_error = mapped_error
                continue
            raise mapped_error from exc

        candidate = structured_payload or final_response_text or fallback_final_text
        if not candidate:
            last_error = HTTPException(status_code=500, detail="The agent returned no final response.")
            if attempt < retries - 1:
                await asyncio.sleep(1 + attempt)
                continue
            raise last_error

        cleaned = _strip_markdown_code_fences(candidate)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            preview = cleaned[:300]
            last_error = HTTPException(
                status_code=500,
                detail=f"Agent returned invalid JSON: {preview}",
            )
            if attempt < retries - 1:
                await asyncio.sleep(1 + attempt)
                continue
            raise last_error from exc

    raise last_error or HTTPException(status_code=500, detail="Agent execution failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes shared runtime services for the FastAPI app."""

    _load_environment()
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )
    place_finder_runner = Runner(
        app_name=APP_NAME,
        agent=place_finder_agent,
        session_service=session_service,
    )
    itinerary_runner = Runner(
        app_name=APP_NAME,
        agent=itinerary_builder_agent,
        session_service=session_service,
    )
    app.state.session_service = session_service
    app.state.runner = runner
    app.state.place_finder_runner = place_finder_runner
    app.state.itinerary_runner = itinerary_runner

    if not _credentials_configured():
        logger.warning(
            "Gemini access is not configured. /find-places will fail until the backend API key is provided."
        )

    yield


app = FastAPI(
    title="Tourist Place Finder Agent",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _frontend_ready() -> bool:
    """Returns whether the bundled frontend is available on disk."""

    return FRONTEND_INDEX.is_file()


if FRONTEND_DIR.is_dir():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.get("/", include_in_schema=False)
async def serve_frontend() -> FileResponse:
    """Serves the bundled frontend application from the same container."""

    if not _frontend_ready():
        raise HTTPException(status_code=404, detail="Frontend bundle is not available.")
    return FileResponse(FRONTEND_INDEX)


@app.get("/app", include_in_schema=False)
async def serve_frontend_alias() -> FileResponse:
    """Serves the bundled frontend from a stable alias path."""

    return await serve_frontend()


@app.get("/health")
async def health() -> dict[str, str]:
    """Returns a basic health check response."""

    return {"status": "ok", "agent": AGENT_NAME}


@app.post("/find-places", response_model=PlaceResponse)
async def find_places(payload: PlaceRequest, request: Request) -> PlaceResponse:
    """Runs the ADK specialist agents sequentially and returns a validated JSON response."""

    if not _credentials_configured():
        raise HTTPException(
            status_code=500,
            detail="Gemini access is not configured. Add the backend API key to backend/.env or Cloud Run.",
        )

    session_service: InMemorySessionService = request.app.state.session_service
    place_finder_runner: Runner = request.app.state.place_finder_runner
    itinerary_runner: Runner = request.app.state.itinerary_runner

    try:
        place_result = await _run_agent_json(
            runner=place_finder_runner,
            session_service=session_service,
            agent_name=PLACE_FINDER_AGENT_NAME,
            payload={
                "city": payload.city, 
                "interest": payload.interest,
                "budget": payload.budget,
                "duration_days": payload.duration_days,
                "group_type": payload.group_type,
                "dates": payload.dates,
                "diet": payload.diet,
                "pace": payload.pace
            },
        )
        places = place_result.get("places", [])
        if not isinstance(places, list) or len(places) == 0:
            raise HTTPException(status_code=500, detail="Place finder did not return any places.")

        place_names = [place.get("name", "") for place in places if isinstance(place, dict)]
        if any(not name for name in place_names):
            raise HTTPException(status_code=500, detail="Place finder returned invalid place objects.")

        itinerary_result = await _run_agent_json(
            runner=itinerary_runner,
            session_service=session_service,
            agent_name=ITINERARY_AGENT_NAME,
            payload={
                "city": payload.city, 
                "interest": payload.interest, 
                "places": place_names,
                "budget": payload.budget,
                "duration_days": payload.duration_days,
                "group_type": payload.group_type,
                "dates": payload.dates,
                "diet": payload.diet,
                "pace": payload.pace
            },
        )

        final_payload = {
            "city": payload.city,
            "interest": payload.interest,
            "places": places,
            "itinerary": _normalize_itinerary_shape(itinerary_result.get("itinerary")),
            "travel_tips": _normalize_tips_shape(itinerary_result.get("travel_tips", [])),
            "weather_context": itinerary_result.get("weather_context"),
            "vlog_links": itinerary_result.get("vlog_links"),
            "generated_at": current_timestamp()["generated_at"],
        }
    except HTTPException as exc:
        logger.warning("Falling back to direct tool pipeline after ADK agent failure: %s", exc.detail)
        try:
            final_payload = _build_tool_fallback_payload(payload.city, payload.interest)
        except Exception as fallback_exc:
            logger.exception("Fallback tool pipeline also failed: %s", fallback_exc)
            raise exc

    try:
        return PlaceResponse.model_validate(final_payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agent response failed validation: {exc}",
        ) from exc




