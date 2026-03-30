"""FunctionTools for itinerary construction and practical travel advice."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ItinerarySlot(BaseModel):
    """One time slot in a one-day itinerary."""

    time: str
    place: str
    activity: str
    travel_note: str


class TimeSlotResult(BaseModel):
    """Structured output for a full-day itinerary."""

    morning: ItinerarySlot
    midmorning: ItinerarySlot
    afternoon: ItinerarySlot
    evening: ItinerarySlot


class TravelTipResult(BaseModel):
    """Structured output for practical travel tips."""

    tips: list[str] = Field(
        min_length=3,
        max_length=3,
        description="Exactly three practical travel tips.",
    )


SLOT_ORDER = (
    ("morning", "8:00 AM - 10:00 AM"),
    ("midmorning", "10:30 AM - 12:30 PM"),
    ("afternoon", "1:30 PM - 4:00 PM"),
    ("evening", "4:30 PM - 7:00 PM"),
)


def _activity_for_place(place: str) -> str:
    """Builds a realistic activity suggestion from a place name."""

    lower_place = place.lower()
    if any(token in lower_place for token in ("falls", "waterfall", "abbi", "cascade")):
        return "Spend time at the viewpoint, walk the surrounding stretch, and pause for photos."
    if any(token in lower_place for token in ("temple", "mandir", "devasthana", "gudi")):
        return "Explore the complex calmly, take in the architecture, and keep the stop unhurried."
    if any(token in lower_place for token in ("fort", "palace", "mahal")):
        return "Walk the main sections, take in the architecture, and pause at the best lookout points."
    if any(token in lower_place for token in ("sanctuary", "reserve", "wildlife", "zoo", "park")):
        return "Keep the pace easy, scan for wildlife or greenery, and allow time for the quieter sections."
    if any(token in lower_place for token in ("peak", "hill", "trek", "trail", "betta", "giri")):
        return "Use this slot for the active stretch, keeping enough buffer for the return leg."
    if any(token in lower_place for token in ("market", "bazaar", "street", "food")):
        return "Use this stop for local bites, browsing, and a slower reset before the next move."
    return "Take a focused visit, enjoy the main highlights, and keep enough buffer for the next transfer."


def _travel_note(index: int, total_stops: int, city: str) -> str:
    """Returns a short travel note between slots."""

    if index == 0:
        return f"Start early in {city} to avoid traffic and keep the rest of the day relaxed."
    if index == total_stops - 1:
        return "Wrap up here and leave buffer for the evening return or dinner plans."
    return "Allow roughly 20 to 30 minutes for the transfer and a short reset before the next stop."


def create_time_slots(places: list[str], city: str) -> dict[str, Any]:
    """Creates realistic one-day time slots for the provided places and city.

    Args:
        places: Exactly five place names from the place finder stage.
        city: The city the itinerary is being planned for.

    Returns:
        A dictionary with the exact shape:
        {
            "morning": {"time": "...", "place": "...", "activity": "...", "travel_note": "..."},
            "midmorning": {"time": "...", "place": "...", "activity": "...", "travel_note": "..."},
            "afternoon": {"time": "...", "place": "...", "activity": "...", "travel_note": "..."},
            "evening": {"time": "...", "place": "...", "activity": "...", "travel_note": "..."}
        }
        Use realistic sequencing and mention travel time between stops.
    """

    selected_places = (places[:4] + places[-1:])[:4]
    itinerary: dict[str, Any] = {}
    total_stops = len(SLOT_ORDER)

    for index, ((slot_name, slot_time), place_name) in enumerate(zip(SLOT_ORDER, selected_places, strict=True)):
        itinerary[slot_name] = {
            "time": slot_time,
            "place": place_name,
            "activity": _activity_for_place(place_name),
            "travel_note": _travel_note(index, total_stops, city),
        }

    return TimeSlotResult.model_validate(itinerary).model_dump()


def add_travel_tips(city: str, interest: str) -> dict[str, Any]:
    """Generates 3 practical travel tips for the city and interest.

    Args:
        city: The destination city.
        interest: The travel interest that the itinerary is optimized for.

    Returns:
        A dictionary with the exact shape:
        {
            "tips": ["tip 1", "tip 2", "tip 3"]
        }
        The list must contain exactly three concise, practical tips.
    """

    interest_lower = interest.lower().strip()
    tips = [
        f"Start early in {city} so transfers feel easier and the day stays flexible.",
        f"Keep small cash, water, and a charged phone handy when exploring {city}.",
        f"If {interest_lower} is your focus, leave one slot slightly open in case a stop deserves more time than planned.",
    ]

    if any(token in interest_lower for token in ("waterfall", "trek", "wildlife", "photography")):
        tips[1] = f"Carry water, a light snack, and grippy footwear if your {city} day includes uneven ground or viewpoints."
    if any(token in interest_lower for token in ("temple", "culture", "heritage")):
        tips[2] = f"Check local timings in {city} before you leave, since temple or heritage access can shift across the day."
    if any(token in interest_lower for token in ("food", "street food", "market")):
        tips[2] = f"Plan your best meal stop in {city} around the local rush so the experience feels fresh and worth the wait."

    return TravelTipResult.model_validate({"tips": tips}).model_dump()
