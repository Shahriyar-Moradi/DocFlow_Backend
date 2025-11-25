"""
Shared helpers for working with Anthropic API responses.
"""
from typing import Optional


def detect_model_not_found_error(error_message: str, model_name: str) -> Optional[str]:
    """
    Return a human-friendly hint if the error text indicates the configured model
    is not available.
    """
    if not error_message:
        return None

    lower_msg = error_message.lower()
    if "not_found" in lower_msg and "model" in lower_msg:
        return (
            f"Anthropic could not find the model '{model_name}'. "
            "Double-check the ANTHROPIC_MODEL environment variable and ensure your "
            "account has access to that model (e.g., claude-sonnet-4-5-20250929 or its alias claude-sonnet-4-5)."
        )
    return None

