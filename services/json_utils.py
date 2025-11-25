import json
import re
from json import JSONDecodeError
from typing import Any, Dict, Optional


def _balance_json_braces(text: str) -> Optional[str]:
    """
    Return the substring spanning from the first opening brace to the matching
    closing brace (supports nested braces). Returns None if not balanced.
    """
    if not text:
        return None

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for idx in range(start, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to extract the first valid JSON object embedded in a string.

    Handles Claude-style markdown code fences (```json ... ```) as well as
    free-form text where JSON is mixed with prose.
    """
    if not text:
        return None

    candidates = []

    # 1) Try fenced code blocks first
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text, re.IGNORECASE)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    # 2) Fallback to balancing braces across the entire text
    balanced = _balance_json_braces(text)
    if balanced:
        candidates.append(balanced.strip())

    for candidate in candidates:
        if not candidate:
            continue
        cleaned = candidate.strip().strip("`")

        try:
            return json.loads(cleaned)
        except JSONDecodeError:
            # Sometimes models wrap JSON in additional prose, try to balance again
            nested = _balance_json_braces(cleaned)
            if nested and nested != cleaned:
                try:
                    return json.loads(nested.strip())
                except JSONDecodeError:
                    continue

    return None

