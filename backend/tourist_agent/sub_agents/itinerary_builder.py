"""Specialist ADK agent that turns place recommendations into a day plan."""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import BaseModel, Field

from tourist_agent.tools.itinerary_tools import add_travel_tips, create_time_slots

DEFAULT_AGENT_MODEL = "openrouter/openrouter/free"


def _model_name() -> str:
    """Returns the normalized LiteLLM model string for the itinerary builder."""

    configured = os.getenv("OPENROUTER_AGENT_MODEL", DEFAULT_AGENT_MODEL).strip() or DEFAULT_AGENT_MODEL
    if configured.startswith("openrouter/"):
        return configured
    return f"openrouter/{configured}"


MODEL = LiteLlm(model=_model_name())


class ItineraryBuilderInput(BaseModel):
    """Structured input accepted by the itinerary builder agent."""

    city: str = Field(description="The city the itinerary is for.")
    interest: str = Field(description="The travel interest that guides the itinerary.")
    places: list[str] = Field(
        min_length=5,
        max_length=5,
        description="Exactly five place names selected by the place finder agent.",
    )


itinerary_builder_agent = LlmAgent(
    name="itinerary_builder_agent",
    model=MODEL,
    description="Builds a realistic one-day itinerary and travel tips from five place names.",
    input_schema=ItineraryBuilderInput,
    instruction="""
You are itinerary_builder_agent, a specialist in practical one-day travel plans.

Follow this workflow exactly:
1. Call create_time_slots with the provided places and city.
2. Call add_travel_tips with the provided city and interest.
3. Return a single JSON object with this exact shape:
   {"city": "...", "interest": "...", "itinerary": {...}, "travel_tips": ["...", "...", "..."]}

Rules:
- Plan realistically and do not cram too many visits into one slot.
- Include a useful travel_note in every slot.
- Output ONLY valid JSON.
- Do not include markdown fences, explanations, or extra keys.
""".strip(),
    tools=[
        FunctionTool(create_time_slots),
        FunctionTool(add_travel_tips),
    ],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        maxOutputTokens=2048,
    ),
)
