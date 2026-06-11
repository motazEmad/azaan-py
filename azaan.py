from datetime import datetime, timedelta
import time
import logging
from typing import Any, Dict, List, Optional

import requests
import pygame

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "https://mawaqit.net/api/2.0/mosque/search"
MOSQUE_SLUG = "masjid-al-ihsaan-rotterdam-rotterdam"
SEARCH_WORD = "rotterdam"

LABELS = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]


def search(word: Optional[str] = None,
           lat: Optional[float] = None,
           lon: Optional[float] = None,
           page: int = 1) -> List[Dict[str, Any]]:
    """Search mawaqit for mosques by word or coordinates."""
    params: Dict[str, Any] = {"page": page}
    if word:
        params["word"] = word
    if lat is not None and lon is not None:
        params["lat"], params["lon"] = lat, lon
    r = requests.get(API_URL, params=params,
                     headers={"Accept": "application/json"}, timeout=10)
    r.raise_for_status()
    return r.json()


def get_mosque(slug: str = MOSQUE_SLUG, word: str = SEARCH_WORD) -> Optional[Dict[str, Any]]:
    """Fetch the target mosque (with today's prayer times) from the API."""
    try:
        results = search(word=word)
    except Exception as e:
        logger.error(f"Failed to fetch mosque data from API: {e}")
        return None

    for mosque in results:
        if mosque.get("slug") == slug:
            return mosque

    logger.error(f"Mosque with slug '{slug}' not found in search results")
    return None


def compare_time_with_now(time_str: str) -> int:
    """
    Compare a given time string in 'hh:mm' format with the current time.

    Args:
        time_str: Time string in 'hh:mm' format.

    Returns:
        A string indicating whether the time is in the past, present, or future.
    """
    now = datetime.now()
    time_to_compare = datetime.strptime(time_str, '%H:%M').replace(year=now.year, month=now.month, day=now.day)

    if time_to_compare < now:
        return -1  # The time is in the past
    elif time_to_compare > now:
        return 1  # The time is in the future
    else:
        return 0  # The time is now


def sleep_until_time(target_time_str: str) -> None:
    """
    Sleep until the specified time in 'hh:mm' format.

    Args:
        target_time_str: Time string in 'hh:mm' format.
    """
    now = datetime.now()
    target_time = datetime.strptime(target_time_str, '%H:%M').replace(year=now.year, month=now.month, day=now.day)

    # If the target time is in the past, set it for the next day
    if target_time < now:
        target_time += timedelta(days=1)

    # Calculate the time to sleep
    sleep_duration = (target_time - now).total_seconds()
    print(f"Sleeping for {sleep_duration} seconds until {target_time_str}...")
    time.sleep(sleep_duration)
    print(f"It's now {target_time_str}! Time to wake up!")


def play_azan(audio_file: str = '1.mp3') -> None:
    """
    Play an audio file and wait until it finishes playing.

    Args:
        audio_file: Path to the audio file to play (default: '1.mp3')
    """
    pygame.mixer.init()
    pygame.mixer.music.load(audio_file)
    pygame.mixer.music.play()

    # Wait until the audio finishes playing
    while pygame.mixer.music.get_busy():
        time.sleep(0.1)  # Check every 100ms if music is still playing


if __name__ == "__main__":

    mosque = get_mosque()
    while mosque is None:
        time.sleep(20)
        mosque = get_mosque()

    while True:
        today_prayer_times = mosque["times"]
        print(f"{mosque['name']}  ({mosque.get('localisation')})")
        print("  ", dict(zip(LABELS, today_prayer_times)), "| Jumua:", mosque.get("jumua"))

        for i in range(len(today_prayer_times)):
            if i == 1:  # skip Sunrise
                continue
            compareTime = compare_time_with_now(today_prayer_times[i])
            if compareTime == -1:
                continue
            sleep_until_time(today_prayer_times[i])
            # Play azan
            play_azan(f"~/Documents/azaan/azaan.mp3")

        sleep_until_time("00:01")  # sleep until the next day to check the new prayer times

        # Refresh times for the new day
        refreshed = get_mosque()
        while refreshed is None:
            time.sleep(20)
            refreshed = get_mosque()
        mosque = refreshed
