"""FunctionTools for discovering and formatting tourist place recommendations."""

from __future__ import annotations

import json
import os
from typing import Any

os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

from litellm import completion
from pydantic import BaseModel, Field

DEFAULT_MODEL = "stepfun/step-3.5-flash:free"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
FALLBACK_MODEL = "openrouter/openrouter/free"


class PlaceNameResult(BaseModel):
    """Structured output for raw place-name discovery."""

    city: str
    interest: str
    places: list[str] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five distinct tourist place names.",
    )


class PlaceDetail(BaseModel):
    """Structured details for a tourist place card."""

    name: str
    description: str
    best_time: str
    entry_fee: str
    tips: str


class PlaceDetailResult(BaseModel):
    """Structured output for enriched place details."""

    places: list[PlaceDetail] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five tourist places with visitor-friendly details.",
    )


def _normalize_openrouter_model(model_name: str) -> str:
    """Returns a model string that LiteLLM can route through OpenRouter."""

    configured = model_name.strip()
    if configured.startswith("openrouter/"):
        return configured
    return f"openrouter/{configured}"


def _api_key() -> str:
    """Returns the configured backend API key for provider-backed tool calls."""

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key or api_key.lower() in {
        "your_openrouter_api_key_here",
        "changeme",
        "replace_me",
    }:
        raise RuntimeError(
            "Backend API key is not configured. Add it to backend/.env or Cloud Run."
        )
    return api_key


def _model_name() -> str:
    """Returns the normalized primary LiteLLM model string for tool-side generation."""

    configured = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return _normalize_openrouter_model(configured)


def _candidate_models() -> list[str]:
    """Returns the primary model followed by a silent backup route."""

    candidates = [_model_name(), _normalize_openrouter_model(FALLBACK_MODEL)]
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _base_url() -> str:
    """Returns the provider base URL used by LiteLLM."""

    return os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL


def _strip_markdown_code_fences(payload: str) -> str:
    """Removes optional Markdown code fences from a model response."""

    stripped = payload.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
    if stripped.endswith("```"):
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def _content_to_text(content: Any) -> str:
    """Normalizes LiteLLM message content into a plain text string."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    fragments.append(str(text))
            elif item is not None:
                fragments.append(str(item))
        return "".join(fragments)
    if content is None:
        return ""
    return str(content)


def _normalize_keys(value: Any) -> Any:
    """Normalizes model-returned JSON keys so schema validation is more forgiving."""

    if isinstance(value, list):
        return [_normalize_keys(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        cleaned_key = str(key).strip().strip(':').replace('-', '_').replace(' ', '_').lower()
        normalized[cleaned_key] = _normalize_keys(item)
    return normalized


def _should_try_fallback(exc: Exception) -> bool:
    """Returns whether a provider failure should trigger the silent backup route."""

    message = str(exc).lower()
    return any(
        token in message
        for token in ("429", "rate limit", "too many requests", "503", "unavailable", "timed out")
    )


def _generate_structured_output(
    *,
    prompt: str,
    schema: type[BaseModel],
    system_instruction: str,
) -> dict[str, Any]:
    """Calls the configured model and validates the JSON response against a schema."""

    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
    request_messages = [
        {"role": "system", "content": system_instruction},
        {
            "role": "user",
            "content": (
                f"{prompt}\n\n"
                "Return exactly one JSON object that validates against this JSON Schema:\n"
                f"{schema_json}\n\n"
                "Do not wrap the JSON in markdown fences and do not add commentary."
            ),
        },
    ]

    last_error = "The configured model returned an empty structured response."
    for model_name in _candidate_models():
        for max_tokens in (2200, 4200):
            try:
                response = completion(
                    model=model_name,
                    api_key=_api_key(),
                    base_url=_base_url(),
                    temperature=0.2,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    messages=request_messages,
                )
            except Exception as exc:
                last_error = str(exc)[:280]
                if _should_try_fallback(exc) and model_name != _candidate_models()[-1]:
                    break
                if _should_try_fallback(exc) and model_name == _candidate_models()[-1]:
                    continue
                raise RuntimeError(last_error) from exc

            choice = response.choices[0]
            raw_text = _strip_markdown_code_fences(_content_to_text(choice.message.content))
            if not raw_text:
                last_error = "The configured model returned an empty structured response."
                if choice.finish_reason == "length":
                    continue
                break
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                last_error = f"The configured model returned invalid JSON: {raw_text[:240]}"
                if choice.finish_reason == "length":
                    continue
                raise RuntimeError(last_error) from exc
            return schema.model_validate(_normalize_keys(parsed)).model_dump()

    raise RuntimeError(last_error)


def _place_category(name: str) -> str:
    """Infers a broad place category from the place name."""

    lower_name = name.lower()
    if any(token in lower_name for token in ("falls", "waterfall", "abbi", "cascade")):
        return "waterfall"
    if any(token in lower_name for token in ("temple", "mandir", "devasthana", "gudi")):
        return "temple"
    if any(token in lower_name for token in ("fort", "palace", "mahal")):
        return "heritage"
    if any(token in lower_name for token in ("sanctuary", "reserve", "wildlife", "zoo", "park")):
        return "wildlife"
    if any(token in lower_name for token in ("peak", "hill", "trek", "trail", "betta", "giri")):
        return "trek"
    if any(token in lower_name for token in ("beach", "lake", "river", "ghat", "viewpoint")):
        return "scenic"
    if any(token in lower_name for token in ("market", "bazaar", "street", "food")):
        return "food"
    if any(token in lower_name for token in ("museum", "gallery", "memorial")):
        return "culture"
    return "landmark"


def _best_time_for_category(category: str) -> str:
    """Returns a visitor-friendly best-time hint for a place category."""

    best_time_map = {
        "waterfall": "Early morning or right after the monsoon",
        "temple": "Early morning or just before sunset",
        "heritage": "Morning to late afternoon",
        "wildlife": "Early morning for the best sightings",
        "trek": "Start early in the morning",
        "scenic": "Sunrise or golden hour",
        "food": "Late morning or evening",
        "culture": "Mid-morning to afternoon",
        "landmark": "Morning or evening",
    }
    return best_time_map.get(category, "Morning or evening")


def _entry_fee_for_category(category: str) -> str:
    """Returns a simple entry fee hint for a place category."""

    fee_map = {
        "waterfall": "Usually free or low local fee",
        "temple": "Usually free; donation optional",
        "heritage": "Check locally",
        "wildlife": "Ticketed entry likely",
        "trek": "Usually free; guide fees may apply",
        "scenic": "Usually free",
        "food": "Pay for what you order",
        "culture": "Check locally",
        "landmark": "Check locally",
    }
    return fee_map.get(category, "Check locally")


def _tip_for_category(category: str) -> str:
    """Returns one practical visitor tip for a place category."""

    tip_map = {
        "waterfall": "Wear grippy footwear and protect electronics from spray.",
        "temple": "Dress modestly and keep cash handy for footwear or donation counters.",
        "heritage": "Carry water and budget extra time for walking between sections.",
        "wildlife": "Arrive early, stay quiet, and carry binoculars if you have them.",
        "trek": "Start early, carry water, and check the trail condition before you head out.",
        "scenic": "Aim for softer light and keep a light layer for breezy viewpoints.",
        "food": "Go during the local rush for fresher specials and faster turnover.",
        "culture": "Check the opening hours before you travel across town.",
        "landmark": "Visit early to avoid both traffic and the busiest photo lines.",
    }
    return tip_map.get(category, "Visit early and confirm local timings before you leave.")


def _description_for_place(name: str, category: str) -> str:
    """Builds a short visitor-friendly description for a place."""

    description_map = {
        "waterfall": (
            f"{name} is a strong pick for travelers who want dramatic scenery, fresh air, and a photogenic stop. "
            "It works especially well on a one-day outing because the experience is memorable without demanding a long, complicated schedule."
        ),
        "temple": (
            f"{name} offers a calm cultural stop with local character and a slower, more reflective pace. "
            "It fits well into a city itinerary because you can enjoy the setting, architecture, and atmosphere in a compact visit."
        ),
        "heritage": (
            f"{name} stands out for travelers who enjoy history, architecture, and a sense of place. "
            "It is usually easy to combine with nearby attractions, making it a practical anchor stop in a one-day plan."
        ),
        "wildlife": (
            f"{name} is a rewarding stop for nature-focused travelers looking for greenery, wildlife, or quieter surroundings. "
            "It is best approached with a little extra time so you can enjoy the setting instead of rushing through it."
        ),
        "trek": (
            f"{name} suits travelers who want a bit of movement, open views, and a more active part of the day. "
            "It is most enjoyable when started early, with enough buffer for the walk and a relaxed return."
        ),
        "scenic": (
            f"{name} is a reliable stop for broad views, a slower pace, and easy photo moments. "
            "It helps balance the itinerary by giving you a visually rewarding break without needing heavy logistics."
        ),
        "food": (
            f"{name} is a solid pick when the day needs a memorable local flavor stop. "
            "It works best when timed around a meal window so the visit feels relaxed and worth the detour."
        ),
        "culture": (
            f"{name} adds context and local character to the trip through stories, objects, or art. "
            "It is a good mid-day stop because you can cover it comfortably and move on without losing momentum."
        ),
        "landmark": (
            f"{name} is one of the more recognizable stops for visitors who want a rounded feel for the destination. "
            "It is easy to include in a one-day route because the visit is straightforward and traveler-friendly."
        ),
    }
    return description_map[category]


def search_places(city: str, interest: str) -> dict[str, Any]:
    """Returns top 5 tourist spots for the given city and interest. Use Gemini knowledge - no external API needed.

    Args:
        city: The city or destination the traveler wants to explore.
        interest: The travel interest to optimize for, such as waterfalls, food,
            temples, wildlife, trekking, or photography.

    Returns:
        A dictionary with the exact shape:
        {
            "city": "<city>",
            "interest": "<interest>",
            "places": ["Place 1", "Place 2", "Place 3", "Place 4", "Place 5"]
        }
        The list must contain exactly five real, distinct, tourist-friendly spots.
    """

    prompt = (
        f"Find exactly five real tourist places in {city} that best match the interest "
        f"'{interest}'. Favor places travelers can actually visit. If there are fewer "
        "than five strong direct matches, include nearby signature spots that still fit "
        "the traveler's intent. Return only the JSON schema."
    )
    return _generate_structured_output(
        prompt=prompt,
        schema=PlaceNameResult,
        system_instruction=(
            "You are a travel research assistant. Return exactly five place names, keep "
            "them distinct, and avoid markdown or commentary."
        ),
    )


def format_place_details(places: list[str]) -> dict[str, Any]:
    """Formats raw place data into structured visitor-friendly details.

    Args:
        places: A list of place names that should be converted into rich tourist
            cards. The list should contain exactly five place names.

    Returns:
        A dictionary with the exact shape:
        {
            "places": [
                {
                    "name": "<place name>",
                    "description": "<2-3 sentence description>",
                    "best_time": "<best time to visit>",
                    "entry_fee": "<fee guidance>",
                    "tips": "<single practical visitor tip>"
                }
            ]
        }
        The response must contain exactly five place objects in the same order as input.
    """

    place_cards = []
    for place_name in places[:5]:
        category = _place_category(place_name)
        place_cards.append(
            {
                "name": place_name,
                "description": _description_for_place(place_name, category),
                "best_time": _best_time_for_category(category),
                "entry_fee": _entry_fee_for_category(category),
                "tips": _tip_for_category(category),
            }
        )

    return PlaceDetailResult.model_validate({"places": place_cards}).model_dump()
