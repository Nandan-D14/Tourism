"""Tools for fetching weather data."""

import os
import requests
import logging

logger = logging.getLogger(__name__)

def get_weather(city: str) -> str:
    """Fetch current weather for the city. Uses OpenWeatherMap if key is provided."""
    api_key = os.getenv("OPENWEATHERMAP_API_KEY")
    
    if api_key:
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
            resp = requests.get(url).json()
            if resp.get("cod") == 200:
                weather_desc = resp["weather"][0]["description"]
                temp = resp["main"]["temp"]
                return f"The current weather in {city} is {temp}°C with {weather_desc}."
        except Exception as e:
            logger.warning(f"Weather API failed: {e}")
            
    # Mock fallback
    return f"The weather in {city} is mostly sunny, around 25°C."
