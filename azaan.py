from datetime import date, datetime, timedelta
import time
import re
import json
import logging
from html.parser import HTMLParser
from typing import Dict, Any, Optional, List
from pathlib import Path

import requests
import pygame

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ScriptParser(HTMLParser):
    """Parse HTML and extract JavaScript from script tags"""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: List[str] = []
        self.in_script: bool = False
        self.current_script: str = ""

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        if tag == "script":
            self.in_script = True
            self.current_script = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False
            if self.current_script.strip():
                self.scripts.append(self.current_script)

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current_script += data


def _parse_json_value(value_str: str) -> Any:
    """
    Parse a string value into appropriate Python type.
    Supports: boolean, number, string, JSON objects/arrays.
    """
    value_str = value_str.strip()

    # Try boolean
    if value_str.lower() == 'true':
        return True
    elif value_str.lower() == 'false':
        return False

    # Try null
    if value_str.lower() == 'null':
        return None

    # Try JSON object/array first
    if (value_str.startswith('{') and value_str.endswith('}')) or \
            (value_str.startswith('[') and value_str.endswith(']')):
        try:
            return json.loads(value_str)
        except json.JSONDecodeError:
            pass

    # Try removing quotes if it's a quoted string
    if (value_str.startswith("'") and value_str.endswith("'")) or \
            (value_str.startswith('"') and value_str.endswith('"')):
        return value_str[1:-1]

    # Try number (int or float)
    try:
        if '.' in value_str:
            return float(value_str)
        else:
            return int(value_str)
    except ValueError:
        pass

    # Return as string
    return value_str


def _extract_object_from_js(js_code: str, start_pos: int) -> Optional[tuple[str, int]]:
    """
    Extract a complete JSON object starting from a given position.
    Returns the JSON string and the position after the closing brace, or None if extraction fails.
    """
    if start_pos >= len(js_code) or js_code[start_pos] != '{':
        return None

    brace_count = 0
    in_string = False
    escape_next = False
    string_char = None

    for i in range(start_pos, len(js_code)):
        char = js_code[i]

        if escape_next:
            escape_next = False
            continue

        if char == '\\':
            escape_next = True
            continue

        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
        elif char == string_char and in_string:
            in_string = False
            string_char = None
        elif not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return js_code[start_pos:i + 1], i + 1

    return None


def extract_json_from_js(js_code: str) -> Dict[str, Any]:
    """
    Extract JSON objects and variables from JavaScript code.

    Handles patterns like:
    - let varName = {...}
    - var varName = {...}
    - const varName = {...}
    - let varName = 'string value'
    - let varName = true/false/null
    - let varName = 123 or 45.67
    """
    result: Dict[str, Any] = {}

    # Pattern to match variable declarations
    pattern = r'(?:let|var|const)\s+(\w+)\s*=\s*'

    matches = re.finditer(pattern, js_code)

    for match in matches:
        var_name = match.group(1)
        start_pos = match.end()

        # Find where the value ends (semicolon or comma at root level)
        value_str = ""
        brace_count = 0
        bracket_count = 0
        in_string = False
        string_char = None
        escape_next = False

        for i in range(start_pos, len(js_code)):
            char = js_code[i]

            if escape_next:
                value_str += char
                escape_next = False
                continue

            if char == '\\' and in_string:
                value_str += char
                escape_next = True
                continue

            if char in ('"', "'") and not in_string:
                in_string = True
                string_char = char
                value_str += char
            elif char == string_char and in_string:
                in_string = False
                string_char = None
                value_str += char
            elif not in_string:
                if char == '{':
                    brace_count += 1
                    value_str += char
                elif char == '}':
                    brace_count -= 1
                    value_str += char
                elif char == '[':
                    bracket_count += 1
                    value_str += char
                elif char == ']':
                    bracket_count -= 1
                    value_str += char
                elif char in (';', ',', '\n') and brace_count == 0 and bracket_count == 0:
                    if char == '\n':
                        continue
                    break
                else:
                    value_str += char
            else:
                value_str += char

        value_str = value_str.strip()

        try:
            # Try to parse the value into appropriate Python type
            parsed_value = _parse_json_value(value_str)
            result[var_name] = parsed_value
            logger.debug(f"Parsed variable '{var_name}': {type(parsed_value).__name__}")
        except Exception as e:
            logger.warning(f"Failed to parse variable '{var_name}': {e}")
            result[var_name] = value_str

    return result


def parse_html_js_variables(html_content: str) -> Dict[int, Dict[str, Any]]:
    """
    Parse HTML content and extract all JavaScript variables from script tags.

    Args:
        html_content: HTML string containing script tags

    Returns:
        Dictionary mapping script index to extracted variables dictionary
    """
    parser = ScriptParser()
    try:
        parser.feed(html_content)
    except Exception as e:
        logger.error(f"Error parsing HTML: {e}")
        return {}

    result: Dict[int, Dict[str, Any]] = {}
    for idx, script in enumerate(parser.scripts):
        variables = extract_json_from_js(script)
        if variables:
            result[idx] = variables
            logger.info(f"Extracted {len(variables)} variables from script #{idx}")

    return result


def parse_html_file(file_path: str) -> Dict[int, Dict[str, Any]]:
    """
    Parse an HTML file and extract JavaScript variables from script tags.

    Args:
        file_path: Path to HTML file

    Returns:
        Dictionary mapping script index to extracted variables dictionary
    """
    try:
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            logger.error(f"File not found: {file_path}")
            return {}

        with open(file_path_obj, 'r', encoding='utf-8') as f:
            html_content = f.read()

        logger.info(f"Parsed HTML file: {file_path}")
        return parse_html_js_variables(html_content)

    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return {}


def extract_and_store_variables(html_content: str) -> Dict[str, Any]:
    """
    Extract all JavaScript variables and return them as a flat dictionary.
    Merges variables from all script tags.

    Args:
        html_content: HTML string containing script tags

    Returns:
        Dictionary with all extracted variables stored as Python objects
    """
    all_scripts = parse_html_js_variables(html_content)
    merged_variables: Dict[str, Any] = {}

    for script_idx, variables in all_scripts.items():
        for var_name, var_value in variables.items():
            if var_name in merged_variables:
                logger.warning(f"Variable '{var_name}' already exists, overwriting")
            merged_variables[var_name] = var_value

    return merged_variables


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


def get_mosque_response() -> str:
    try:
        response = requests.get(url)
        response.raise_for_status()
        example_html = response.text
    except Exception as e:
        logger.error(f"Failed to fetch HTML from {url}: {e}")
        example_html = ""
    return example_html

url = "https://mawaqit.net/en/masjid-al-ihsaan-rotterdam-rotterdam"
if __name__ == "__main__":

    response = get_mosque_response()

    while response == "":
        time.sleep(20)
        response = get_mosque_response()

    now = date.today()
    month = now.month
    day = now.day

    print(f"Today's date: {month}/{day}")

    all_vars = extract_and_store_variables(response)

    if 'confData' in all_vars:
        conf_data = all_vars['confData']
        calendar = conf_data.get('calendar')

        while True:
            thismonth = calendar[month - 1]
            todayPrayerTimes = thismonth.get(str(day))
            for i in range(todayPrayerTimes.__len__()):
                if i == 1:
                    continue
                compareTime = compare_time_with_now(todayPrayerTimes[i])
                if compareTime == -1:
                    continue
                sleep_until_time(todayPrayerTimes[i])
                # Play azan
                play_azan(f"~/Documents/azaan/azaan.mp3")
            sleep_until_time("00:01")  # sleep until the next day to check the new prayer times



