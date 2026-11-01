"""Groq audio transcription for incoming channel attachments."""

from __future__ import annotations

from pathlib import Path

import httpx


class GroqTranscriptionProvider:
    """Transcribe audio, returning an empty string when transcription is unavailable."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or "").strip()

    async def transcribe(self, file_path: str | Path) -> str:
        """Send an audio attachment to Groq and return its transcript."""
        if not self._api_key:
            return ""

        try:
            path = Path(file_path)
            with path.open("rb") as audio:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        data={"model": "whisper-large-v3"},
                        files={"file": (path.name, audio)},
                    )
                    response.raise_for_status()
                    payload = response.json()
        except (OSError, ValueError, httpx.HTTPError):
            return ""

        text = payload.get("text") if isinstance(payload, dict) else None
        return text.strip() if isinstance(text, str) else ""
