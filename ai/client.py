"""Anthropic SDK wrapper — singleton client. Phase 4."""
import os
import anthropic

_client: anthropic.Anthropic | None = None
MODEL = "claude-sonnet-4-6"


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client
