from fastapi import HTTPException
from llmai.shared import AzureOpenAIClientConfig, ClientConfig, OpenAIApiType

from utils.get_env import (
    get_azure_openai_api_key_env,
    get_azure_openai_api_version_env,
    get_azure_openai_base_url_env,
    get_azure_openai_deployment_env,
    get_azure_openai_endpoint_env,
    get_disable_thinking_env,
)
from utils.llm_provider import get_llm_provider
from utils.parsers import parse_bool_or_none


def disable_thinking() -> bool:
    return parse_bool_or_none(get_disable_thinking_env()) or False


def get_llm_config() -> ClientConfig:
    get_llm_provider()
    api_key = get_azure_openai_api_key_env()
    api_version = get_azure_openai_api_version_env()
    endpoint = get_azure_openai_endpoint_env()
    base_url = get_azure_openai_base_url_env()
    deployment = get_azure_openai_deployment_env()

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Azure OpenAI API Key is not set",
        )
    if not api_version:
        raise HTTPException(
            status_code=400,
            detail="Azure OpenAI API Version is not set",
        )
    if not endpoint and not base_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "Azure OpenAI endpoint is not set. "
                "Configure AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_BASE_URL."
            ),
        )

    return AzureOpenAIClientConfig(
        api_type=OpenAIApiType.RESPONSES,
        api_key=api_key,
        api_version=api_version,
        endpoint=endpoint or None,
        base_url=base_url or None,
        deployment=deployment or None,
    )
