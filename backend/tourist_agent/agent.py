"""Root ADK agent that orchestrates place discovery and itinerary planning."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from tourist_agent.sub_agents.itinerary_builder import itinerary_builder_agent
from tourist_agent.sub_agents.place_finder import place_finder_agent

DEFAULT_AGENT_MODEL = "openrouter/openrouter/free"


def _model_name() -> str:
    """Returns the normalized LiteLLM model string for the orchestrator."""

    configured = (
        os.getenv("OPENROUTER_AGENT_MODEL")
        or os.getenv("OPENROUTER_MODEL")
        or DEFAULT_AGENT_MODEL
    ).strip() or DEFAULT_AGENT_MODEL
    if configured.startswith("openrouter/"):
        return configured
    return f"openrouter/{configured}"


MODEL = LiteLlm(model=_model_name())


def current_timestamp() -> dict[str, str]:
    """Returns the current UTC timestamp in ISO 8601 format for the final generated_at field.

    Returns:
        A dictionary with the exact shape:
        {
            "generated_at": "2026-03-29T18:30:00Z"
        }
    """

    return {
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    }


root_agent = LlmAgent(
    name="tourist_place_finder",
    model=MODEL,
    description="Coordinates tourist place discovery and one-day itinerary planning.",
    sub_agents=[place_finder_agent, itinerary_builder_agent],
    instruction="""
You are tourist_place_finder, the orchestration agent for a Tourist Place Finder app.

Workflow:
1. Parse the user's message to identify the city and the travel interest.
2. Call place_finder_agent first with {"city": "...", "interest": "..."}.
3. Read the five place names from the JSON returned by place_finder_agent.
4. Call itinerary_builder_agent next with {"city": "...", "interest": "...", "places": ["...", "...", "...", "...", "..."]}.
5. Call current_timestamp and use its generated_at value.
6. Return exactly one JSON object with this shape:
   {
     "city": "...",
     "interest": "...",
     "places": [ { "name": "...", "description": "...", "best_time": "...", "entry_fee": "...", "tips": "..." } ],
     "itinerary": {
       "morning": { "time": "...", "place": "...", "activity": "...", "travel_note": "..." },
       "midmorning": { "time": "...", "place": "...", "activity": "...", "travel_note": "..." },
       "afternoon": { "time": "...", "place": "...", "activity": "...", "travel_note": "..." },
       "evening": { "time": "...", "place": "...", "activity": "...", "travel_note": "..." }
     },
     "travel_tips": ["...", "...", "..."],
     "generated_at": "..."
   }

Rules:
- Output ONLY valid JSON.
- Do not use markdown fences, prose, or explanatory text.
- Preserve the exact five place objects returned by place_finder_agent.
- Use the itinerary and travel_tips returned by itinerary_builder_agent.
- generated_at must come from current_timestamp.
- If the user already gave a city and interest, do not ask follow-up questions.
""".strip(),
    tools=[
        AgentTool(place_finder_agent, skip_summarization=True),
        AgentTool(itinerary_builder_agent, skip_summarization=True),
        FunctionTool(current_timestamp),
    ],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
        maxOutputTokens=3072,
    ),
)
