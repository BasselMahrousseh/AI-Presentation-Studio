import asyncio

import pytest

from utils.model_availability import check_llm_and_image_provider_api_or_model_availability


def _set_azure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM", "azure")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")


def test_skips_image_provider_when_generation_disabled(monkeypatch):
    _set_azure_env(monkeypatch)
    monkeypatch.setenv("DISABLE_IMAGE_GENERATION", "true")
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)

    asyncio.run(check_llm_and_image_provider_api_or_model_availability())


def test_skips_invalid_image_provider_when_generation_disabled(monkeypatch):
    _set_azure_env(monkeypatch)
    monkeypatch.setenv("DISABLE_IMAGE_GENERATION", "true")
    monkeypatch.setenv("IMAGE_PROVIDER", "not-a-real-provider")

    asyncio.run(check_llm_and_image_provider_api_or_model_availability())


def test_requires_image_provider_when_generation_enabled(monkeypatch):
    _set_azure_env(monkeypatch)
    monkeypatch.delenv("DISABLE_IMAGE_GENERATION", raising=False)
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)

    with pytest.raises(Exception, match="IMAGE_PROVIDER must be provided"):
        asyncio.run(check_llm_and_image_provider_api_or_model_availability())


def test_requires_azure_credentials(monkeypatch):
    _set_azure_env(monkeypatch)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY")
    monkeypatch.setenv("DISABLE_IMAGE_GENERATION", "true")

    with pytest.raises(Exception, match="Azure OpenAI API Key is not set"):
        asyncio.run(check_llm_and_image_provider_api_or_model_availability())


def test_rejects_non_azure_provider(monkeypatch):
    _set_azure_env(monkeypatch)
    monkeypatch.setenv("LLM", "openai")
    monkeypatch.setenv("DISABLE_IMAGE_GENERATION", "true")

    with pytest.raises(Exception, match="Studio only supports azure"):
        asyncio.run(check_llm_and_image_provider_api_or_model_availability())
