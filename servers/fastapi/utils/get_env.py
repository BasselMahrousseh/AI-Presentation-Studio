import os
from pathlib import Path

DEFAULT_PRESENTON_OAUTH_ISSUER = "https://api.presenton.ai"
DEFAULT_PRESENTON_OAUTH_CLIENT_ID = "ptc_presenton_open_source"


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_database_url_env():
    return os.getenv("DATABASE_URL")


def get_app_data_directory_env():
    # Durable local storage must never live inside TempFileService's cleanup root.
    return (os.getenv("APP_DATA_DIRECTORY") or "").strip() or str(
        Path(__file__).resolve().parents[1] / "app_data"
    )


def get_fastapi_public_base_url() -> str | None:
    """
    Public origin where FastAPI serves /app_data and /static (no trailing slash).

    Uses NEXT_PUBLIC_FAST_API (same value Electron and the export runtime inject for the UI).
    When unset, callers keep path-only URLs for same-origin / reverse-proxy setups (e.g. Docker).
    """
    v = (os.getenv("NEXT_PUBLIC_FAST_API") or "").strip().rstrip("/")
    return v or None


def get_temp_directory_env():
    return os.getenv("TEMP_DIRECTORY")


def get_disable_auth_env():
    return os.getenv("DISABLE_AUTH")


def is_disable_auth_enabled():
    return _is_truthy(get_disable_auth_env())


def get_llm_provider_env():
    return os.getenv("LLM")


def get_openai_api_key_env():
    return os.getenv("OPENAI_API_KEY")


def get_google_api_key_env():
    return os.getenv("GOOGLE_API_KEY")


def get_azure_openai_api_key_env():
    return os.getenv("AZURE_OPENAI_API_KEY")


def get_azure_openai_model_env():
    return os.getenv("AZURE_OPENAI_MODEL")


def get_azure_openai_endpoint_env():
    return os.getenv("AZURE_OPENAI_ENDPOINT")


def get_azure_openai_base_url_env():
    return os.getenv("AZURE_OPENAI_BASE_URL")


def get_azure_openai_api_version_env():
    return os.getenv("AZURE_OPENAI_API_VERSION")


def get_azure_openai_deployment_env():
    return os.getenv("AZURE_OPENAI_DEPLOYMENT")


def get_pexels_api_key_env():
    return os.getenv("PEXELS_API_KEY")


def get_disable_image_generation_env():
    return os.getenv("DISABLE_IMAGE_GENERATION")


def is_parallel_image_generation_enabled() -> bool:
    """Whether image provider requests may run concurrently.

    Parallel generation is the existing behavior, so it remains enabled unless
    ENABLE_PARALLEL_IMAGE_GENERATION is explicitly set to a falsey value.
    """
    return _is_truthy(os.getenv("ENABLE_PARALLEL_IMAGE_GENERATION", "true"))


def get_image_provider_env():
    return os.getenv("IMAGE_PROVIDER")


def get_pixabay_api_key_env():
    return os.getenv("PIXABAY_API_KEY")


def get_disable_thinking_env():
    return os.getenv("DISABLE_THINKING")


def get_web_search_provider_env():
    return os.getenv("WEB_SEARCH_PROVIDER")


def get_web_search_max_results_env():
    return os.getenv("WEB_SEARCH_MAX_RESULTS")


def get_searxng_base_url_env():
    return os.getenv("SEARXNG_BASE_URL")


def get_tavily_api_key_env():
    return os.getenv("TAVILY_API_KEY")


def get_exa_api_key_env():
    return os.getenv("EXA_API_KEY")


def get_brave_search_api_key_env():
    return os.getenv("BRAVE_SEARCH_API_KEY")


def get_serper_api_key_env():
    return os.getenv("SERPER_API_KEY")


def get_comfyui_url_env():
    return os.getenv("COMFYUI_URL")


def get_comfyui_workflow_env():
    return os.getenv("COMFYUI_WORKFLOW")


# Dalle 3 Quality
def get_dall_e_3_quality_env():
    return os.getenv("DALL_E_3_QUALITY")


# Gpt Image 1.5 Quality
def get_gpt_image_1_5_quality_env():
    return os.getenv("GPT_IMAGE_1_5_QUALITY")


# Codex OAuth
def get_migrate_database_on_startup_env():
    return os.getenv("MIGRATE_DATABASE_ON_STARTUP")


def get_sentry_dsn_env():
    return os.getenv("SENTRY_DSN")


def get_sentry_traces_sample_rate_env():
    return os.getenv("SENTRY_TRACES_SAMPLE_RATE")


def get_sentry_send_default_pii_env():
    return os.getenv("SENTRY_SEND_DEFAULT_PII")


# Open WebUI Image Provider
def get_open_webui_image_url_env():
    return os.getenv("OPEN_WEBUI_IMAGE_URL")


def get_open_webui_image_api_key_env():
    return os.getenv("OPEN_WEBUI_IMAGE_API_KEY")


# OpenAI Compatible Image Provider
def get_openai_compat_image_base_url_env():
    return os.getenv("OPENAI_COMPAT_IMAGE_BASE_URL")


def get_openai_compat_image_api_key_env():
    return os.getenv("OPENAI_COMPAT_IMAGE_API_KEY")


def get_openai_compat_image_model_env():
    return os.getenv("OPENAI_COMPAT_IMAGE_MODEL")


def get_studio_service_api_key_env():
    """Shared secret the Workspace backend authenticates with (its PRESENTATION_STUDIO_API_KEY)."""
    return os.getenv("STUDIO_SERVICE_API_KEY")
