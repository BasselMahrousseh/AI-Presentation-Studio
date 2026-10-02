import pytest
from fastapi import HTTPException

from services.chat.service import validate_chat_presentation_type


def test_outline_chat_allowed_on_smart_record_from_workspace_handoff():
    # A Workspace chat hand-off creates the record as Smart and opens it on the
    # outline page, whose chat sends presentation_type="standard".
    validate_chat_presentation_type("standard", "smart")


@pytest.mark.parametrize(
    ("presentation_type", "generation_mode"),
    [("standard", "standard"), ("smart", "smart")],
)
def test_matching_types_allowed(presentation_type, generation_mode):
    validate_chat_presentation_type(presentation_type, generation_mode)


@pytest.mark.parametrize("generation_mode", ["standard", None])
def test_smart_chat_rejected_on_non_smart_record(generation_mode):
    with pytest.raises(HTTPException) as exc_info:
        validate_chat_presentation_type("smart", generation_mode)
    assert exc_info.value.status_code == 400
