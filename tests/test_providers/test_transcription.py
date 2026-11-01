"""Transcription request and attachment fallback behavior without external requests."""

from pathlib import Path

import httpx
import pytest

from openharness.providers.transcription import GroqTranscriptionProvider


@pytest.mark.asyncio
async def test_transcribe_sends_audio_model_and_auth(tmp_path: Path, monkeypatch):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"sample-audio-content")
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": "  Hello from the attachment.\n"})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "openharness.providers.transcription.httpx.AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs),
    )

    result = await GroqTranscriptionProvider(api_key="test-key").transcribe(audio)

    assert result == "Hello from the attachment."
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert request.headers["Content-Type"].startswith("multipart/form-data;")
    assert b'name="model"\r\n\r\nwhisper-large-v3' in request.content
    assert b'name="file"; filename="voice.ogg"' in request.content
    assert b"sample-audio-content" in request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, "", "   "])
async def test_transcribe_without_key_does_not_create_client(tmp_path: Path, monkeypatch, api_key):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"sample-audio")

    def unexpected_client(**kwargs):
        raise AssertionError("A missing key must not create a client or send audio")

    monkeypatch.setattr("openharness.providers.transcription.httpx.AsyncClient", unexpected_client)

    assert await GroqTranscriptionProvider(api_key=api_key).transcribe(audio) == ""


@pytest.mark.asyncio
async def test_transcribe_missing_attachment_does_not_create_client(tmp_path: Path, monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError("A missing attachment must not create a client")

    monkeypatch.setattr("openharness.providers.transcription.httpx.AsyncClient", unexpected_client)

    result = await GroqTranscriptionProvider(api_key="test-key").transcribe(tmp_path / "missing.ogg")

    assert result == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": "unavailable"}),
        httpx.Response(200, content=b"invalid-json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"text": None}),
        httpx.Response(200, json=[]),
    ],
    ids=["http-failure", "invalid-json", "missing-text", "invalid-text", "invalid-payload"],
)
async def test_transcribe_bad_response_returns_empty(tmp_path: Path, monkeypatch, response):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"sample-audio")
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "openharness.providers.transcription.httpx.AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(lambda request: response), **kwargs),
    )

    assert await GroqTranscriptionProvider(api_key="test-key").transcribe(audio) == ""


@pytest.mark.asyncio
async def test_transcribe_network_failure_returns_empty(tmp_path: Path, monkeypatch):
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"sample-audio")

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection unavailable", request=request)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "openharness.providers.transcription.httpx.AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handle), **kwargs),
    )

    assert await GroqTranscriptionProvider(api_key="test-key").transcribe(audio) == ""
