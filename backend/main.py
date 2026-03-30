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
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)

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


class PlaceCard(BaseModel):
    """One tourist place returned to the frontend."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    best_time: str
    entry_fee: str
    tips: str


class ItinerarySlot(BaseModel):
    """One slot in the day itinerary."""

    model_config = ConfigDict(extra="forbid")

    time: str
    place: str
    activity: str
    travel_note: str


class Itinerary(BaseModel):
    """The four-slot itinerary returned by the agent."""

    model_config = ConfigDict(extra="forbid")

    morning: ItinerarySlot
    midmorning: ItinerarySlot
    afternoon: ItinerarySlot
    evening: ItinerarySlot


class PlaceResponse(BaseModel):
    """Final API response returned by the Tourist Place Finder app."""

    model_config = ConfigDict(extra="forbid")

    city: str
    interest: str
    places: list[PlaceCard] = Field(min_length=5, max_length=5)
    itinerary: Itinerary
    travel_tips: list[str] = Field(min_length=3, max_length=3)
    generated_at: str


def _load_environment() -> None:
    """Loads the backend environment file for local development."""

    load_dotenv(BASE_DIR / ".env", override=False)


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

    search_result = search_places(city, interest)
    place_names = search_result.get("places")
    if not isinstance(place_names, list) or len(place_names) != 5:
        raise HTTPException(status_code=500, detail="Fallback place search did not return exactly five places.")

    place_details = format_place_details(place_names)
    itinerary = create_time_slots(place_names, city)
    travel_tips = add_travel_tips(city, interest)
    return {
        "city": city,
        "interest": interest,
        "places": place_details.get("places"),
        "itinerary": itinerary,
        "travel_tips": travel_tips.get("tips"),
        "generated_at": current_timestamp()["generated_at"],
    }


async def _run_agent_json(
    *,
    runner: Runner,
    session_service: InMemorySessionService,
    agent_name: str,
    payload: dict[str, object],
    retries: int = 3,
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
            async for event in events:
                function_payload = _extract_function_payload(event)
                if function_payload:
                    structured_payload = function_payload

                text_payload = _extract_text_payload(event)
                if text_payload:
                    fallback_final_text = text_payload
                    if event.author == agent_name and event.is_final_response():
                        final_response_text = text_payload
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
            payload={"city": payload.city, "interest": payload.interest},
        )
        places = place_result.get("places")
        if not isinstance(places, list) or len(places) != 5:
            raise HTTPException(status_code=500, detail="Place finder did not return exactly five places.")

        place_names = [place.get("name", "") for place in places if isinstance(place, dict)]
        if len(place_names) != 5 or any(not name for name in place_names):
            raise HTTPException(status_code=500, detail="Place finder returned invalid place objects.")

        itinerary_result = await _run_agent_json(
            runner=itinerary_runner,
            session_service=session_service,
            agent_name=ITINERARY_AGENT_NAME,
            payload={"city": payload.city, "interest": payload.interest, "places": place_names},
        )

        final_payload = {
            "city": payload.city,
            "interest": payload.interest,
            "places": places,
            "itinerary": itinerary_result.get("itinerary"),
            "travel_tips": itinerary_result.get("travel_tips"),
            "generated_at": current_timestamp()["generated_at"],
        }
    except HTTPException as exc:
        logger.warning("Falling back to direct tool pipeline after ADK agent failure: %s", exc.detail)
        final_payload = _build_tool_fallback_payload(payload.city, payload.interest)

    try:
        return PlaceResponse.model_validate(final_payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agent response failed validation: {exc}",
        ) from exc




