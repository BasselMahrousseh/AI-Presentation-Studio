import asyncio
import io
import json
import os
import stat
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from openai import APIError as OpenAIAPIError

from models.image_prompt import ImagePrompt
from models.sql.slide import SlideModel
from models.sse_response import (
    SSECompleteResponse,
    SSEErrorResponse,
    SSEStatusResponse,
    SSETraceResponse,
    SSEResponse,
)
from services.chat.conversation_store import ChatConversationStore
from services.export_task_service import EXPORT_TASK_SERVICE
from utils import ocr_language
from utils.datetime_utils import get_current_utc_datetime
from utils.export_utils import export_presentation
from utils.file_utils import (
    get_file_name_with_random_uuid,
)
from utils.image_provider import (
    get_selected_image_provider,
    is_comfyui_selected,
    is_dalle3_selected,
    is_gemini_flash_selected,
    is_gpt_image_1_5_selected,
    is_image_generation_disabled,
    is_nanobanana_pro_selected,
    is_open_webui_selected,
    is_pixabay_selected,
    is_pixels_selected,
)
from utils.llm_client_error_handler import handle_llm_client_exceptions
from utils.parsers import parse_bool_or_none
from utils.path_helpers import get_resource_path, get_writable_path
from utils.sse import safe_sse_stream

_ALL_IMAGE_PROVIDER_PREDICATES = (
    is_pixels_selected,
    is_pixabay_selected,
    is_gemini_flash_selected,
    is_nanobanana_pro_selected,
    is_dalle3_selected,
    is_gpt_image_1_5_selected,
    is_comfyui_selected,
    is_open_webui_selected,
)


def _parse_sse_frame(blob: str) -> tuple[str, dict]:
    """Parse a single SSEResponse / derivative frame (event + JSON data)."""
    text = blob.strip()
    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("event: ")
    assert lines[1].startswith("data: ")
    event = lines[0].removeprefix("event: ")
    raw_data = lines[1].removeprefix("data: ")
    return event, json.loads(raw_data)


def test_get_current_utc_datetime_is_timezone_aware():
    dt = get_current_utc_datetime()
    assert dt.tzinfo is not None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("true", True),
        ("TRUE", True),
        ("TrUe", True),
        ("false", False),
        ("FALSE", False),
        ("", False),
        ("yes", False),
        ("1", False),
        ("\tfalse\n", False),
    ],
)
def test_parse_bool_or_none(value: str | None, expected):
    assert parse_bool_or_none(value) is expected


def test_image_prompt_with_theme_formats_prompt():
    p = ImagePrompt(prompt="lake", theme_prompt="muted colors")
    assert p.get_image_prompt(with_theme=False) == "lake"
    assert p.get_image_prompt(with_theme=True) == "lake, muted colors"


def test_slide_model_get_new_slide_branches():
    pid = uuid.uuid4()
    base = SlideModel(
        presentation=pid,
        layout_group="g",
        layout="l",
        index=2,
        content={"a": 1},
        html_content="<div>slide</div>",
        speaker_note="n",
        properties={"x": True},
        ui={"id": "layout-1", "components": []},
    )
    assert base.get_new_slide(pid, None).content == {"a": 1}
    assert base.get_new_slide(pid, {"b": 2}).content == {"b": 2}
    assert base.get_new_slide(pid).ui == {"id": "layout-1", "components": []}
    assert base.get_new_slide(pid).html_content == "<div>slide</div>"


def test_sse_response_frame_format():
    raw = SSEResponse(event="evt", data="{}").to_string()
    assert raw == "event: evt\ndata: {}\n\n"


def test_sse_typed_frames_encode_json_payloads():
    event, data = _parse_sse_frame(SSEStatusResponse(status="ok").to_string())
    assert event == "response"
    assert data == {"type": "status", "status": "ok"}

    event, data = _parse_sse_frame(SSETraceResponse(trace={"x": 1}).to_string())
    assert event == "response"
    assert data == {"type": "trace", "trace": {"x": 1}}

    event, data = _parse_sse_frame(SSEErrorResponse(detail="bad").to_string())
    assert event == "response"
    assert data == {"type": "error", "detail": "bad"}

    event, data = _parse_sse_frame(
        SSECompleteResponse(key="k", value={"v": 1}).to_string()
    )
    assert event == "response"
    assert data == {"type": "complete", "k": {"v": 1}}


def test_safe_sse_stream_converts_late_exception_to_error_frame():
    async def broken_stream():
        yield SSEResponse(
            event="response",
            data=json.dumps({"type": "chunk"}),
        ).to_string()
        raise RuntimeError("provider failed")

    async def collect():
        chunks = []
        async for chunk in safe_sse_stream(
            broken_stream(),
            logger=MagicMock(),
            error_detail="Stream failed",
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect())
    assert len(chunks) == 2
    event, data = _parse_sse_frame(chunks[-1])
    assert event == "response"
    assert data == {"type": "error", "detail": "Stream failed"}


def test_chat_conversation_store_ensure_conversation_id():
    store = ChatConversationStore(sql_session=None)  # type: ignore[arg-type]
    nid = asyncio.run(store.ensure_conversation_id(None))
    assert isinstance(nid, uuid.UUID)
    cid = uuid.uuid4()
    assert asyncio.run(store.ensure_conversation_id(cid)) == cid


def test_get_resource_path_resolves_under_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    resolved = get_resource_path("static/a.txt")
    assert resolved == os.path.abspath(os.path.join(str(tmp_path), "static/a.txt"))


def test_get_writable_path_app_data_fallback(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    monkeypatch.delenv("APP_DATA_DIRECTORY", raising=False)
    base = tmp_path / "appdata"
    base.mkdir()
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(base))
    ad_path = get_writable_path("nested/dir")
    assert os.path.abspath(ad_path).startswith(os.path.abspath(str(base)))

    monkeypatch.delenv("APP_DATA_DIRECTORY", raising=False)
    cwd_path = get_writable_path("other/dir")
    assert cwd_path.startswith(os.path.abspath(str(tmp_path)))


@pytest.mark.parametrize(
    ("env_provider", "predicate"),
    [
        ("pexels", is_pixels_selected),
        ("pixabay", is_pixabay_selected),
        ("gemini_flash", is_gemini_flash_selected),
        ("nanobanana_pro", is_nanobanana_pro_selected),
        ("dall-e-3", is_dalle3_selected),
        ("gpt-image-1.5", is_gpt_image_1_5_selected),
        ("comfyui", is_comfyui_selected),
        ("open_webui", is_open_webui_selected),
    ],
)
def test_image_provider_env_flags_exclusive(monkeypatch, env_provider: str, predicate):
    monkeypatch.setenv("IMAGE_PROVIDER", env_provider)
    assert predicate() is True
    for other in _ALL_IMAGE_PROVIDER_PREDICATES:
        if other is not predicate:
            assert other() is False


def test_get_selected_image_provider_none(monkeypatch):
    monkeypatch.delenv("IMAGE_PROVIDER", raising=False)
    assert get_selected_image_provider() is None


def test_get_selected_image_provider_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError):
        get_selected_image_provider()


@pytest.mark.parametrize(
    ("language", "code"),
    [
        ("English", "eng"),
        ("english", "eng"),
        (None, "eng"),
        ("   ", "eng"),
        ("Hausa (Hausa)", "hau"),
    ],
)
def test_presentation_language_to_ocr_resolution(language: str | None, code: str):
    assert ocr_language.presentation_language_to_ocr_code(language) == code


def test_presentation_language_invalid_code_fallback(monkeypatch):
    monkeypatch.setitem(
        ocr_language.PRESENTATION_LANGUAGE_TO_TESSERACT,
        "__bad_lang__",
        "not valid!",
    )
    assert ocr_language.presentation_language_to_ocr_code("__bad_lang__") == "eng"


def test_handle_llm_client_exceptions(monkeypatch):
    monkeypatch.setattr(
        handle_llm_client_exceptions.__globals__["traceback"],
        "print_exc",
        lambda: None,
    )
    assert (
        handle_llm_client_exceptions(HTTPException(status_code=401, detail="auth")).detail
        == "auth"
    )

    from google.genai.errors import APIError as GoogleAPIError
    from llmai.shared.errors import BaseError as LLMAIBaseError
    from utils.provider_error_messages import INVALID_API_KEY_MESSAGE

    llmai_err = LLMAIBaseError(status_code=429, message="busy")
    assert handle_llm_client_exceptions(llmai_err).detail == "busy"

    wrapped_auth_err = LLMAIBaseError(
        status_code=401,
        message=(
            "Error code: 401 - {'error': {'message': "
            "'Incorrect API key provided: sk-proj-secret', "
            "'code': 'invalid_api_key'}}"
        ),
    )
    wrapped_auth_response = handle_llm_client_exceptions(wrapped_auth_err)
    assert wrapped_auth_response.detail == INVALID_API_KEY_MESSAGE
    assert "sk-proj" not in wrapped_auth_response.detail

    assert "OpenAI API request failed" in handle_llm_client_exceptions(
        OpenAIAPIError(
            message="boom",
            request=httpx.Request("POST", "https://x"),
            body=None,
        )
    ).detail

    assert "Google API error" in handle_llm_client_exceptions(
        GoogleAPIError(503, {})
    ).detail

    generic = handle_llm_client_exceptions(ValueError("oops"))
    assert generic.detail.startswith("LLM API error")


def test_export_includes_optional_fastapi_param():
    async def runner():
        fake_result = MagicMock(path="/exports/deck.pdf")
        dummy = uuid.uuid4()
        mock_pdf = AsyncMock(return_value=fake_result)
        with patch.dict(
            os.environ,
            {
                "NEXT_PUBLIC_URL": "https://next.example",
                "NEXT_PUBLIC_FAST_API": "https://fast.example",
            },
            clear=False,
        ), patch.object(EXPORT_TASK_SERVICE, "export_from_url", mock_pdf):
            await export_presentation(
                dummy,
                title="safe",
                export_as="pdf",
                cookie_header="presenton_session=abc; theme=dark",
            )

        pdf_call = mock_pdf.await_args.kwargs
        assert "pdf-maker" in pdf_call["url"]
        assert (
            "#exportCookie=presenton_session%3Dabc%3B+theme%3Ddark"
            in pdf_call["url"]
        )
        assert pdf_call["fastapi_url"] == "https://fast.example"
        assert pdf_call["cookie_header"] == "presenton_session=abc; theme=dark"

        mock_pptx = AsyncMock(return_value=fake_result)
        with patch.dict(
            os.environ, {"NEXT_PUBLIC_FAST_API": ""}, clear=False
        ), patch.object(EXPORT_TASK_SERVICE, "export_from_url", mock_pptx):
            await export_presentation(dummy, title="two", export_as="pptx")
        pptx_call = mock_pptx.await_args.kwargs
        assert "#" not in pptx_call["url"]
        assert pptx_call["fastapi_url"] is None

    asyncio.run(runner())


def test_export_task_output_permissions_are_readable(tmp_path):
    export_dir = tmp_path / "exports"
    export_dir.mkdir(mode=0o700)
    output_path = export_dir / "deck.pptx"
    output_path.write_bytes(b"pptx")
    os.chmod(export_dir, 0o700)
    os.chmod(output_path, 0o600)

    EXPORT_TASK_SERVICE._ensure_output_readable(str(output_path))

    assert stat.S_IMODE(export_dir.stat().st_mode) == 0o755
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o644


def test_get_file_name_with_random_uuid_variants():
    from starlette.datastructures import UploadFile as StarletteUploadFile

    upload_like = StarletteUploadFile(filename="slide.png", file=io.BytesIO(b"x"))
    out_upload = get_file_name_with_random_uuid(upload_like)
    assert out_upload.endswith(".png") and "----" in out_upload

    disk_path_out = get_file_name_with_random_uuid("/tmp/report.pdf")
    assert disk_path_out.endswith(".pdf") and "----" in disk_path_out

    assert "----" in get_file_name_with_random_uuid(io.BytesIO(b"z"))


@pytest.mark.parametrize(
    "raw",
    ["true", "TRUE", "TrUe"],
)
def test_is_image_generation_disabled_truthy(monkeypatch, raw: str):
    monkeypatch.setenv("DISABLE_IMAGE_GENERATION", raw)
    assert is_image_generation_disabled() is True


@pytest.mark.parametrize(
    "raw",
    [None, "", "false", "0", "maybe"],
)
def test_is_image_generation_disabled_falsey(monkeypatch, raw: str | None):
    if raw is None:
        monkeypatch.delenv("DISABLE_IMAGE_GENERATION", raising=False)
    else:
        monkeypatch.setenv("DISABLE_IMAGE_GENERATION", raw)
    assert is_image_generation_disabled() is False
