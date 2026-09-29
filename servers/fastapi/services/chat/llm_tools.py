from llmai.shared import Tool  # type: ignore[import-not-found]


def build_chat_llm_tools(function_tools: list[Tool]) -> list[Tool]:
    """
    Chat uses function tools only. Web search, when the chat's web search mode allows
    it, is the searchWeb function tool (ChatTools), not a provider-native search tool.
    """
    return list(function_tools)
