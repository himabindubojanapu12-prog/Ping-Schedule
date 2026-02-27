"""
LLM Client — Anthropic Claude integration
Used by the agent to parse natural language availability from emails.
"""

import os
import json


class LLMClient:
    """
    Wraps Anthropic Claude API for natural language parsing.
    Supports mock mode for testing without API key.
    """

    def __init__(self, api_key: str = None, model: str = "claude-haiku-4-5-20251001"):
        self.api_key = api_key or os.environ.get("API_KEY")
        self.model = model
        self._client = None

        if self.api_key:
            try:
                import {anthropic}
                self._client = anthropic.Anthropic(api_key=self.api_key)
                print(f"[LLM] Using Claude {model}")
            except ImportError:
                print("[LLM] anthropic package not found. Using mock mode.")
        else:
            print("[LLM] No API key found. Using mock mode.")

    def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        if self._client is None:
            return self._mock_complete(prompt)

        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _mock_complete(self, prompt: str) -> str:
        """Return realistic mock responses for testing."""
        prompt_lower = prompt.lower()

        if "monday" in prompt_lower or "tuesday" in prompt_lower or "available" in prompt_lower:
            return json.dumps({
                "action": "provide_availability",
                "slots": [
                    {"date": "2025-03-10", "start_time": "10:00", "end_time": "11:00", "timezone": "UTC"},
                    {"date": "2025-03-11", "start_time": "14:00", "end_time": "15:00", "timezone": "UTC"},
                ],
                "message": "Candidate provided availability",
            })
        elif "confirm" in prompt_lower or "perfect" in prompt_lower or "works" in prompt_lower:
            return json.dumps({
                "action": "confirm",
                "slots": [],
                "message": "Candidate confirmed the proposed time",
            })
        elif "decline" in prompt_lower or "not interested" in prompt_lower:
            return json.dumps({
                "action": "decline",
                "slots": [],
                "message": "Candidate declined",
            })
        else:
            return json.dumps({
                "action": "provide_availability",
                "slots": [
                    {"date": "2025-03-12", "start_time": "09:00", "end_time": "10:00", "timezone": "UTC"},
                ],
                "message": "Parsed availability from email",
            })
