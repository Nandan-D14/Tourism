"""Tools for finding media like Vlogs and using Web Search for local events."""

import os
import logging
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

def web_search_events(city: str) -> str:
    """Uses DuckDuckGo to search for current events in the given city."""
    try:
        results = DDGS().text(f"current events this weekend in {city}", max_results=3)
        if results:
            events = [res['title'] for res in results]
            return f"Found recent events in {city}: " + ", ".join(events)
    except Exception as e:
        logger.warning(f"DDGS failed to find events: {e}")
        
    return f"No major real-time events found for {city} right now."

def fetch_youtube_vlogs(city: str) -> list[str]:
    """Mock implementation to fetch YouTube vlogs."""
    api_key = os.getenv("YOUTUBE_API_KEY")
    if api_key:
        pass # Optional: Implement real YouTube Data API v3 search here
        
    return [
       f"https://www.youtube.com/results?search_query={city.replace(' ', '+')}+travel+vlog"
    ]
