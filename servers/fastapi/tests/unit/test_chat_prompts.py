from services.chat.prompts import _trim_block, build_system_prompt


def test_trim_block_returns_empty_for_blank_text():
    assert _trim_block("label", "") == ""
    assert _trim_block("label", "   \n\t") == ""


def test_build_system_prompt_includes_trimmed_memory_blocks():
    system_prompt = build_system_prompt(
        presentation_memory_context="  Prior deck decision  ",
        chat_memory_context="\nEarlier user request\n",
    )

    assert "Deck memory (background only; may be partial or stale):" in system_prompt
    assert "Chat memory (earlier messages in this conversation):" in system_prompt
    assert "\nPrior deck decision\n" in system_prompt
    assert "\nEarlier user request\n" in system_prompt


def test_build_system_prompt_omits_empty_memory_blocks():
    system_prompt = build_system_prompt("", " ")

    assert "Deck memory (background only; may be partial or stale):" not in system_prompt
    assert "Chat memory (earlier messages in this conversation):" not in system_prompt
    assert "Tool Protocol" in system_prompt


def test_standard_presentations_get_the_outline_only_prompt():
    system_prompt = build_system_prompt("", "")

    assert "presentation outline AI assistant" in system_prompt
    assert "use addOutline, updateOutline, and deleteOutline only" in system_prompt
    # No TemplateV2 slide-editing tools remain for standard (outline-draft) presentations.
    assert "getAvailableBlocks" not in system_prompt
    assert "addElement" not in system_prompt


def test_smart_presentations_get_the_smart_prompt():
    system_prompt = build_system_prompt("", "", presentation_type="smart")

    assert "presentation outline AI assistant" not in system_prompt
    assert "saveSlide" in system_prompt
