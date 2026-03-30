"""Specialist ADK agent that turns place recommendations into a day plan."""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import BaseModel, Field

from tourist_agent.tools.itinerary_tools import add_travel_tips, create_time_slots, get_additional_context

DEFAULT_AGENT_MODEL = "openrouter/openrouter/free"


def _model_name() -> str:
    """Returns the normalized LiteLLM model string for the itinerary builder."""

    configured = (
        os.getenv("OPENROUTER_AGENT_MODEL")
        or os.getenv("OPENROUTER_MODEL")
        or DEFAULT_AGENT_MODEL
    ).strip() or DEFAULT_AGENT_MODEL
    if configured.startswith("openrouter/"):
        return configured
    return f"openrouter/{configured}"


MODEL = LiteLlm(model=_model_name())


class ItineraryBuilderInput(BaseModel):
    """Structured input accepted by the itinerary builder agent."""

    city: str = Field(description="The city the itinerary is for.")
    interest: str = Field(description="The travel interest that guides the itinerary.")
    places: list[str] = Field(description="Place names selected by the place finder agent.")
    budget: str = Field(default="Mid-range", description="Travel budget.")
    duration_days: int = Field(default=1, description="Number of days.")
    group_type: str = Field(default="solo", description="Group type.")


itinerary_builder_agent = LlmAgent(
    name="itinerary_builder_agent",
    model=MODEL,
    description="Builds a realistic itinerary, travel tips, and adds context from places.",
    input_schema=ItineraryBuilderInput,
    instruction="""
You are itinerary_builder_agent, a specialist in practical travel plans.

Follow this workflow exactly:
1. Call get_additional_context with the city to determine weather and events.
2. Call create_time_slots with the provided places, city, and duration_days. Incorporate the weather/events context intelligently.
3. Call add_travel_tips with the provided city, interest, budget, and group_type.
4. Return a single JSON object with this exact shape:
   {"city": "...", "interest": "...", "budget": "...", "group_type": "...", "itinerary": [...], "travel_tips": ["...", "...", "..."], "weather_context": "...", "vlog_links": ["..."]}

Rules:
- Give a list of day objects in `itinerary` if duration is > 1. Each day must contain morning, midmorning, afternoon, evening. Output MUST match `list[DayItinerary]` shape. If it's 1 day, returning a list with 1 element is required!
- Include a useful travel_note in every slot (routing info, budget info).
- Output ONLY valid JSON.
- Do not include markdown fences, explanations, or extra keys.
""".strip(),
    tools=[
        FunctionTool(get_additional_context),
        FunctionTool(create_time_slots),
        FunctionTool(add_travel_tips),
    ],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        maxOutputTokens=2048,
    ),
)
