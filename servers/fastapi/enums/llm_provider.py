from enum import Enum


class LLMProvider(Enum):
    # Studio runs on Azure OpenAI only. The enum is kept so provider-aware helpers
    # (llmai's reasoning support lookup, web-search routing) keep a typed value.
    AZURE = "azure"
