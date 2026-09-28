from fastapi import HTTPException

from enums.image_provider import ImageProvider
from utils.get_env import (
    get_openai_api_key_env,
    get_pixabay_api_key_env,
    get_pexels_api_key_env,
    get_comfyui_url_env,
    get_comfyui_workflow_env,
)
from utils.get_env import get_google_api_key_env
from utils.llm_config import get_llm_config
from utils.image_provider import (
    get_selected_image_provider,
    is_image_generation_disabled,
)


def _check_image_provider_configuration() -> None:
    selected_image_provider = get_selected_image_provider()
    if not selected_image_provider:
        raise Exception("IMAGE_PROVIDER must be provided")

    if selected_image_provider == ImageProvider.PEXELS:
        pexels_api_key = get_pexels_api_key_env()
        if not pexels_api_key:
            raise Exception("PEXELS_API_KEY must be provided")

    elif selected_image_provider == ImageProvider.PIXABAY:
        pixabay_api_key = get_pixabay_api_key_env()
        if not pixabay_api_key:
            raise Exception("PIXABAY_API_KEY must be provided")

    elif (
        selected_image_provider == ImageProvider.GEMINI_FLASH
        or selected_image_provider == ImageProvider.NANOBANANA_PRO
    ):
        google_api_key = get_google_api_key_env()
        if not google_api_key:
            raise Exception("GOOGLE_API_KEY must be provided")

    elif (
        selected_image_provider == ImageProvider.DALLE3
        or selected_image_provider == ImageProvider.GPT_IMAGE_1_5
    ):
        openai_api_key = get_openai_api_key_env()
        if not openai_api_key:
            raise Exception("OPENAI_API_KEY must be provided")

    elif selected_image_provider == ImageProvider.COMFYUI:
        comfyui_url = get_comfyui_url_env()
        if not comfyui_url:
            raise Exception("COMFYUI_URL must be provided")
        workflow_json = get_comfyui_workflow_env()
        if not workflow_json:
            raise Exception("COMFYUI_WORKFLOW must be provided")


async def check_llm_and_image_provider_api_or_model_availability():
    """Fail startup on missing Azure OpenAI or image-provider configuration (env only)."""
    try:
        get_llm_config()
    except HTTPException as exc:
        raise Exception(exc.detail) from exc
    if not is_image_generation_disabled():
        _check_image_provider_configuration()
