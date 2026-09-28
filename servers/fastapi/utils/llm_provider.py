from fastapi import HTTPException

from constants.llm import DEFAULT_AZURE_MODEL
from enums.llm_provider import LLMProvider
from utils.get_env import (
    get_azure_openai_deployment_env,
    get_azure_openai_model_env,
    get_llm_provider_env,
)


def get_llm_provider() -> LLMProvider:
    # Azure OpenAI is the only supported provider. LLM may be left unset; any other value is a
    # misconfiguration, rejected loudly rather than silently falling back to Azure.
    configured = (get_llm_provider_env() or LLMProvider.AZURE.value).strip().lower()
    if configured != LLMProvider.AZURE.value:
        raise HTTPException(
            status_code=500,
            detail=f"Unsupported LLM provider '{configured}'. Studio only supports azure.",
        )
    return LLMProvider.AZURE


def get_model() -> str:
    get_llm_provider()
    return (
        get_azure_openai_model_env()
        or get_azure_openai_deployment_env()
        or DEFAULT_AZURE_MODEL
    )
