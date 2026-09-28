import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from openai import AuthenticationError, BadRequestError, RateLimitError

from models.image_prompt import ImagePrompt
from services.image_generation_service import ImageGenerationService
from utils.get_env import is_parallel_image_generation_enabled
from utils.image_generation_error import normalize_image_generation_error
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.provider_error_messages import (
    IMAGE_MODERATION_MESSAGE,
    INVALID_API_KEY_MESSAGE,
)


def _quota_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    response = httpx.Response(429, request=request)
    return RateLimitError(
        "You exceeded your current quota.",
        response=response,
        body={
            "error": {
                "message": "You exceeded your current quota.",
                "code": "insufficient_quota",
            }
        },
    )


def _auth_error() -> AuthenticationError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(401, request=request)
    return AuthenticationError(
        "Error code: 401 - Incorrect API key provided: sk-proj-secret",
        response=response,
        body={
            "error": {
                "message": "Incorrect API key provided: sk-proj-secret",
                "type": "authentication_error",
                "code": "invalid_api_key",
            }
        },
    )


def _moderation_error() -> BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        "Error code: 400 - moderation_blocked public-figure",
        response=response,
        body={
            "error": {
                "message": "Your request was rejected by the safety system.",
                "type": "image_generation_user_error",
                "code": "moderation_blocked",
                "moderation_details": {
                    "moderation_stage": "input",
                    "categories": ["public-figure"],
                },
            }
        },
    )


def test_normalize_image_generation_error_preserves_openai_quota_status():
    normalized = normalize_image_generation_error(_quota_error())

    assert normalized.status_code == 429
    assert "API quota is unavailable" in normalized.detail
    assert "billing" in normalized.detail


def test_normalize_openai_auth_error_hides_raw_provider_response():
    normalized = normalize_image_generation_error(_auth_error())

    assert normalized.status_code == 401
    assert normalized.detail == INVALID_API_KEY_MESSAGE
    assert "sk-proj" not in normalized.detail
    assert "invalid_api_key" not in normalized.detail


def test_normalize_openai_moderation_error_hides_raw_provider_response():
    normalized = normalize_image_generation_error(_moderation_error())

    assert normalized.status_code == 400
    assert normalized.detail == IMAGE_MODERATION_MESSAGE
    assert "moderation_blocked" not in normalized.detail
    assert "public-figure" not in normalized.detail


def test_llm_error_handler_preserves_openai_quota_status():
    normalized = handle_llm_client_exceptions(_quota_error())

    assert normalized.status_code == 429
    assert "API quota is unavailable" in normalized.detail


def test_llm_error_handler_hides_openai_auth_raw_provider_response():
    normalized = handle_llm_client_exceptions(_auth_error())

    assert normalized.status_code == 401
    assert normalized.detail == INVALID_API_KEY_MESSAGE
    assert "sk-proj" not in normalized.detail
    assert "invalid_api_key" not in normalized.detail


def test_image_generation_service_raises_provider_error_instead_of_placeholder():
    service = object.__new__(ImageGenerationService)
    service.output_directory = "/tmp"
    service.is_image_generation_disabled = False
    service.is_stock_provider_selected = lambda: False
    service.image_gen_func = AsyncMock(side_effect=_quota_error())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.generate_image(ImagePrompt(prompt="business dashboard")))

    assert exc.value.status_code == 429
    assert "billing" in exc.value.detail


def test_image_generation_service_preserves_existing_http_exception():
    service = object.__new__(ImageGenerationService)
    service.output_directory = "/tmp"
    service.is_image_generation_disabled = False
    service.is_stock_provider_selected = lambda: False
    provider_error = HTTPException(status_code=401, detail="Invalid provider key")
    service.image_gen_func = AsyncMock(side_effect=provider_error)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.generate_image(ImagePrompt(prompt="business dashboard")))

    assert exc.value is provider_error


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, True),
        ("true", True),
        ("1", True),
        ("false", False),
        ("0", False),
    ],
)
def test_parallel_image_generation_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("ENABLE_PARALLEL_IMAGE_GENERATION", raising=False)
    else:
        monkeypatch.setenv("ENABLE_PARALLEL_IMAGE_GENERATION", raw)

    assert is_parallel_image_generation_enabled() is expected


