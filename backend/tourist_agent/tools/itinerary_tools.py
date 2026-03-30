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
        description="Practical travel tips.",
    )


class DayItinerary(BaseModel):
    day: int
    morning: ItinerarySlot
    midmorning: ItinerarySlot
    afternoon: ItinerarySlot
    evening: ItinerarySlot

class MultiDayTimeSlotResult(BaseModel):
    itinerary: list[DayItinerary]

SLOT_ORDER = (
    ("morning", "8:00 AM - 10:00 AM"),
    ("midmorning", "10:30 AM - 12:30 PM"),
    ("afternoon", "1:30 PM - 4:00 PM"),
    ("evening", "4:30 PM - 7:00 PM"),
)


def get_additional_context(city: str) -> dict[str, Any]:
    """Fetches contextual data like weather and recent events or vlogs for a city."""
    from tourist_agent.tools.weather_tools import get_weather
    from tourist_agent.tools.media_tools import web_search_events, fetch_youtube_vlogs
    
    weather = get_weather(city)
    events = web_search_events(city)
    vlogs = fetch_youtube_vlogs(city)
    
    return {
        "weather": weather,
        "events": events,
        "vlogs": vlogs
    }


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


def create_time_slots(places: list[str], city: str, duration_days: int = 1) -> dict[str, Any]:
    """Creates realistic time slots given a list of places.

    Args:
        places: Place names.
        city: The city the itinerary is being planned for.
        duration_days: Days to plan.
    """
    
    itinerary_days: list[dict[str, Any]] = []
    
    total_stops = len(SLOT_ORDER)
    places_per_day = 4
    
    for day_index in range(duration_days):
        day_places = places[day_index * places_per_day : (day_index + 1) * places_per_day]
        # Pad if not enough places
        while len(day_places) < places_per_day:
            day_places.append("Relaxing at hotel or exploring local streets")
            
        daily_slot: dict[str, Any] = {"day": day_index + 1}
        for index, ((slot_name, slot_time), place_name) in enumerate(zip(SLOT_ORDER, day_places, strict=False)):
            daily_slot[slot_name] = {
                "time": slot_time,
                "place": place_name,
                "activity": _activity_for_place(place_name),
                "travel_note": _travel_note(index, total_stops, city),
            }
        
        itinerary_days.append(daily_slot)

    return MultiDayTimeSlotResult.model_validate({"itinerary": itinerary_days}).model_dump()


def add_travel_tips(city: str, interest: str, budget: str = "Mid-range", group_type: str = "solo") -> dict[str, Any]:
    """Generates practical travel tips for the city and interest."""

    interest_lower = interest.lower().strip()
    tips = [
        f"Start early in {city} so transfers feel easier and the day stays flexible.",
        f"For a {group_type} trip on a {budget} budget, plan your meals ahead.",
        f"Keep small cash, water, and a charged phone handy when exploring {city}."
    ]

    if any(token in interest_lower for token in ("waterfall", "trek", "wildlife", "photography")):
        tips[1] = f"Carry water, a light snack, and grippy footwear if your {city} day includes uneven ground or viewpoints."
    if any(token in interest_lower for token in ("temple", "culture", "heritage")):
        tips[2] = f"Check local timings in {city} before you leave, since temple or heritage access can shift across the day."
    if any(token in interest_lower for token in ("food", "street food", "market")):
        tips[2] = f"Plan your best meal stop in {city} around the local rush so the experience feels fresh and worth the wait."

    return TravelTipResult.model_validate({"tips": tips}).model_dump()
