"""Specialist ADK agent that finds and structures five tourist places."""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import BaseModel, Field

from tourist_agent.tools.place_tools import format_place_details, search_places

DEFAULT_AGENT_MODEL = "openrouter/openrouter/free"


def _model_name() -> str:
    """Returns the normalized LiteLLM model string for the place finder."""

    configured = os.getenv("OPENROUTER_AGENT_MODEL", DEFAULT_AGENT_MODEL).strip() or DEFAULT_AGENT_MODEL
    if configured.startswith("openrouter/"):
        return configured
    return f"openrouter/{configured}"


MODEL = LiteLlm(model=_model_name())


class PlaceFinderInput(BaseModel):
    """Structured input accepted by the place finder agent."""

    city: str = Field(description="The city or destination to explore.")
    interest: str = Field(
        description="The travel interest such as waterfalls, temples, food, wildlife, or trekking."
    )


place_finder_agent = LlmAgent(
    name="place_finder_agent",
    model=MODEL,
    description="Finds the best five tourist places for a city and interest, then formats them.",
    input_schema=PlaceFinderInput,
    instruction="""
You are place_finder_agent, a tourism recommendation specialist.

Follow this workflow exactly:
1. Call search_places with the provided city and interest.
2. Call format_place_details with the five place names returned by search_places.
3. Return a single JSON object with this exact shape:
   {"city": "...", "interest": "...", "places": [ ... ]}

Rules:
- Always return exactly 5 places.
- Output ONLY valid JSON.
- Do not include markdown fences, explanations, or extra keys.
- Every place object must include name, description, best_time, entry_fee, and tips.
- Every description must be 2-3 sentences.
""".strip(),
    tools=[
        FunctionTool(search_places),
        FunctionTool(format_place_details),
    ],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        maxOutputTokens=2048,
    ),
)
