from llmai.shared import AzureOpenAIClientConfig, OpenAIApiType

from utils.llm_config import get_llm_config
from utils.llm_provider import get_model


def _set_azure_env(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "deck-deployment")


def test_azure_config_uses_the_responses_api(monkeypatch):
    _set_azure_env(monkeypatch)
    monkeypatch.delenv("LLM", raising=False)

    config = get_llm_config()

    assert isinstance(config, AzureOpenAIClientConfig)
    assert config.api_type == OpenAIApiType.RESPONSES
    assert config.deployment == "deck-deployment"


def test_model_falls_back_to_the_deployment_name(monkeypatch):
    _set_azure_env(monkeypatch)
    monkeypatch.delenv("AZURE_OPENAI_MODEL", raising=False)

    assert get_model() == "deck-deployment"
