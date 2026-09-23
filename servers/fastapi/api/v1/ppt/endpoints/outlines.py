import asyncio
import json
import logging
import traceback
import uuid
from typing import Optional
import dirtyjson
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from constants.presentation import MAX_NUMBER_OF_SLIDES
from models.extraction_quality import (
    AcknowledgeQualityFlagGroupsRequest,
    group_quality_flags,
)
from models.presentation_outline_model import PresentationOutlineModel
from models.sql.presentation import PresentationModel
from models.sse_response import (
    SSECompleteResponse,
    SSEErrorResponse,
    SSEQualityFlagsResponse,
    SSEResponse,
    SSEStatusResponse,
)
from services.temp_file_service import TEMP_FILE_SERVICE
from services.database import get_async_session
from services.document_fact_dedup_service import build_deduplicated_context
from services.documents_loader import DocumentsLoader
from services.mem0_presentation_memory_service import (
    MEM0_PRESENTATION_MEMORY_SERVICE,
)
from utils.llm_utils import message_content_to_text
from utils.outline_utils import (
    detect_explicit_slide_count,
    get_no_of_outlines_to_generate_for_n_slides,
    get_presentation_title_from_presentation_outline,
)
from utils.outline_limits import normalize_outline_payload
from utils.llm_calls.generate_presentation_outlines import (
    OutlineGenerationStatus,
    generate_ppt_outline,
    get_messages as get_outline_messages,
)
from utils.sse import safe_sse_stream
from utils.web_search import get_selected_web_search_provider, get_web_search_route

OUTLINES_ROUTER = APIRouter(prefix="/outlines", tags=["Outlines"])
LOGGER = logging.getLogger(__name__)


def _get_n_slides_to_generate_from_detected_structure(
    presentation: PresentationModel,
) -> Optional[int]:
    """Recompute how many outline slides an explicit "Slide N:"-structured
    presentation's content calls for, or None if the content doesn't show
    that pattern.

    Safe to call on every request for the same presentation: content is set
    once at creation and never mutated afterwards by this endpoint or by
    PUT /outlines/{id}, and detect_explicit_slide_count() is a pure, cheap
    regex scan with no I/O - so this is deliberately recomputed fresh on
    every call rather than persisted, unlike has_explicit_slide_structure
    itself (see the branch logic in stream_outlines() below).
    """
    detected_content_slides = detect_explicit_slide_count(presentation.content)
    if detected_content_slides is None:
        return None

    # Content that already declares its own "Slide N -" sections gets
    # exactly that many outline slides - no synthesized title item added
    # on top. A dedicated title/cover slide is a template-level concern
    # (e.g. the e& brand template already splices in its own fixed
    # cover/thank-you slides outside the outline entirely), not something
    # the outline itself should invent when the user has already laid out
    # their own slides.
    detected_total_slides = min(detected_content_slides, MAX_NUMBER_OF_SLIDES)
    return get_no_of_outlines_to_generate_for_n_slides(
        n_slides=detected_total_slides,
        toc=presentation.include_table_of_contents,
        title_slide=presentation.include_title_slide,
    )


@OUTLINES_ROUTER.get("/{id}", response_model=PresentationOutlineModel)
async def get_outline(
    id: uuid.UUID,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    if not presentation.outlines:
        return PresentationOutlineModel(slides=[])

    return PresentationOutlineModel(**presentation.outlines)


@OUTLINES_ROUTER.put("/{id}", response_model=PresentationOutlineModel)
async def update_outline(
    id: uuid.UUID,
    outline: PresentationOutlineModel,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    presentation.outlines = outline.model_dump(mode="json")
    presentation.n_slides = len(outline.slides)
    presentation.title = get_presentation_title_from_presentation_outline(outline)

    sql_session.add(presentation)
    await sql_session.commit()

    await MEM0_PRESENTATION_MEMORY_SERVICE.store_generated_outlines(
        presentation.id,
        presentation.outlines,
    )

    return outline


@OUTLINES_ROUTER.post("/{id}/quality-flags/acknowledge")
async def acknowledge_quality_flag_groups(
    id: uuid.UUID,
    payload: AcknowledgeQualityFlagGroupsRequest,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    acknowledged = set(presentation.acknowledged_quality_flag_groups or [])
    acknowledged.update(payload.group_keys)
    presentation.acknowledged_quality_flag_groups = sorted(acknowledged)

    sql_session.add(presentation)
    await sql_session.commit()

    return {
        "acknowledged_quality_flag_groups": presentation.acknowledged_quality_flag_groups
    }


@OUTLINES_ROUTER.get("/stream/{id}")
async def stream_outlines(
    id: uuid.UUID,
    request: Request,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await sql_session.get(PresentationModel, id)

    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    search_route, actual_search_provider = get_web_search_route()
    LOGGER.info(
        "Starting outline stream: presentation_id=%s web_search_enabled=%s "
        "selected_web_search_provider=%s web_search_route=%s actual_web_search_provider=%s",
        presentation.id,
        presentation.web_search,
        get_selected_web_search_provider().value,
        search_route,
        (
            actual_search_provider.value
            if actual_search_provider
            else ("model-native" if search_route == "native" else "none")
        ),
    )

    temp_dir = TEMP_FILE_SERVICE.create_temp_dir()

    async def inner():
        if await request.is_disconnected():
            return

        yield SSEStatusResponse(
            status="Preparing your presentation outline"
        ).to_string()

        additional_context = ""
        if presentation.file_paths:
            documents_loader = DocumentsLoader(
                file_paths=presentation.file_paths,
                presentation_language=presentation.language,
            )
            await documents_loader.load_documents(temp_dir)
            documents = documents_loader.documents
            if documents:
                additional_context = await build_deduplicated_context(
                    presentation.file_paths,
                    documents,
                    documents_loader.structured_pptx_data,
                    disconnect_checker=request.is_disconnected,
                )

            # Recomputed fresh on every call (deterministic from the same source
            # files, unlike has_explicit_slide_structure) - safe to just overwrite.
            # acknowledged_quality_flag_groups is never touched here; only the
            # dedicated acknowledge endpoint below mutates it.
            presentation.source_quality_flags = [
                flag.model_dump(mode="json") for flag in documents_loader.quality_flags
            ]
            sql_session.add(presentation)
            await sql_session.commit()

            quality_flag_groups = group_quality_flags(
                documents_loader.quality_flags,
                presentation.acknowledged_quality_flag_groups,
            )
            if quality_flag_groups:
                yield SSEQualityFlagsResponse(
                    groups=[group.model_dump(mode="json") for group in quality_flag_groups]
                ).to_string()

        presentation_outlines_text = ""

        if presentation.has_explicit_slide_structure is not None:
            # Detection already ran and was persisted on an earlier call to
            # this endpoint for this presentation (a frontend reconnect
            # retry, a manual page reload, etc.) - reuse that decision
            # verbatim instead of re-deriving it from presentation.n_slides,
            # which this same endpoint's own success path backfills from 0
            # to the real generated slide count below. Re-deriving from
            # n_slides here would silently flip this decision on every call
            # after the first (see BUG_REPORT_has_explicit_slide_structure_
            # idempotency.md). n_slides_to_generate itself is still
            # recomputed fresh on every call, since it's per-call LLM-prompt
            # input, not persisted state.
            has_explicit_slide_structure = presentation.has_explicit_slide_structure
            if has_explicit_slide_structure:
                n_slides_to_generate = (
                    _get_n_slides_to_generate_from_detected_structure(presentation)
                )
            elif presentation.n_slides > 0:
                n_slides_to_generate = get_no_of_outlines_to_generate_for_n_slides(
                    n_slides=presentation.n_slides,
                    toc=presentation.include_table_of_contents,
                    title_slide=presentation.include_title_slide,
                )
            else:
                n_slides_to_generate = None
        elif presentation.n_slides > 0:
            # First call for this presentation. An explicit user-provided
            # slide count at creation time wins over content-based structure
            # detection - existing, deliberate product behavior, unchanged
            # by this fix.
            has_explicit_slide_structure = False
            n_slides_to_generate = get_no_of_outlines_to_generate_for_n_slides(
                n_slides=presentation.n_slides,
                toc=presentation.include_table_of_contents,
                title_slide=presentation.include_title_slide,
            )
        else:
            # First call for this presentation, no explicit slide count -
            # detect whether the content declares its own "Slide N:"
            # structure.
            n_slides_to_generate = _get_n_slides_to_generate_from_detected_structure(
                presentation
            )
            has_explicit_slide_structure = n_slides_to_generate is not None

        # Suppress the title-slide prompt directives for this generation only
        # when explicit slide structure was detected - the presentation's own
        # stored include_title_slide is left untouched for everything else.
        effective_include_title_slide = (
            presentation.include_title_slide and not has_explicit_slide_structure
        )

        outline_messages = get_outline_messages(
            presentation.content,
            n_slides_to_generate,
            presentation.language,
            additional_context,
            presentation.tone,
            presentation.verbosity,
            presentation.instructions,
            effective_include_title_slide,
            presentation.include_table_of_contents,
            has_explicit_slide_structure,
        )
        await MEM0_PRESENTATION_MEMORY_SERVICE.store_generation_context(
            presentation_id=presentation.id,
            system_prompt=(
                message_content_to_text(outline_messages[0].content)
                if len(outline_messages) > 0
                else None
            ),
            user_prompt=(
                message_content_to_text(outline_messages[1].content)
                if len(outline_messages) > 1
                else None
            ),
            extracted_document_text=additional_context,
            source_content=presentation.content,
            instructions=presentation.instructions,
        )

        async for chunk in generate_ppt_outline(
            presentation.content,
            n_slides_to_generate,
            presentation.language,
            additional_context,
            presentation.tone,
            presentation.verbosity,
            presentation.instructions,
            effective_include_title_slide,
            presentation.web_search,
            presentation.include_table_of_contents,
            emit_statuses=True,
            disconnect_checker=request.is_disconnected,
            has_explicit_slide_structure=has_explicit_slide_structure,
        ):
            # Give control to the event loop
            await asyncio.sleep(0)

            if isinstance(chunk, OutlineGenerationStatus):
                LOGGER.info(
                    "Outline generation status: presentation_id=%s status=%s",
                    presentation.id,
                    chunk.message,
                )
                yield SSEStatusResponse(status=chunk.message).to_string()
                continue

            if isinstance(chunk, HTTPException):
                yield SSEErrorResponse(detail=chunk.detail).to_string()
                return

            yield SSEResponse(
                event="response",
                data=json.dumps({"type": "chunk", "chunk": chunk}),
            ).to_string()

            presentation_outlines_text += chunk

        try:
            presentation_outlines_json = dict(
                dirtyjson.loads(presentation_outlines_text)
            )
        except Exception as e:
            traceback.print_exc()
            yield SSEErrorResponse(
                detail=f"Failed to generate presentation outlines. Please try again. {str(e)}",
            ).to_string()
            return

        presentation_outlines = PresentationOutlineModel(
            **normalize_outline_payload(
                presentation_outlines_json,
                MAX_NUMBER_OF_SLIDES,
            )
        )

        if (
            n_slides_to_generate is not None
            and len(presentation_outlines.slides) != n_slides_to_generate
        ):
            yield SSEErrorResponse(
                detail=(
                    "Failed to generate presentation outlines with requested "
                    "number of slides. Please try again."
                )
            ).to_string()
            return

        if n_slides_to_generate is not None:
            presentation_outlines.slides = presentation_outlines.slides[
                :n_slides_to_generate
            ]

        if presentation.n_slides <= 0:
            presentation.n_slides = len(presentation_outlines.slides)

        if presentation.has_explicit_slide_structure is None:
            # Persist the explicit-structure decision exactly once, right
            # alongside the n_slides backfill above and in the same commit -
            # every later call to this endpoint for this presentation must
            # see a non-None value here and reuse it (see the branch logic
            # above) rather than re-deriving it.
            presentation.has_explicit_slide_structure = has_explicit_slide_structure

        presentation.outlines = presentation_outlines.model_dump()
        presentation.mark_outline_generated()
        presentation.title = get_presentation_title_from_presentation_outline(
            presentation_outlines
        )

        sql_session.add(presentation)
        await sql_session.commit()

        await MEM0_PRESENTATION_MEMORY_SERVICE.store_generated_outlines(
            presentation.id,
            presentation.outlines,
        )

        yield SSECompleteResponse(
            key="presentation",
            value={
                **presentation.model_dump(mode="json"),
                # Backed by a real persisted column as of the
                # has_explicit_slide_structure idempotency fix -
                # presentation.model_dump() above already includes the same
                # value under this same key. Kept as an explicit override
                # for clarity and because it's cheap, not because it's still
                # ephemeral. Lets the outline-review page know not to ask
                # for a synthesized title slide when it later kicks off
                # Smart generation from this outline (a dedicated cover
                # slide would either duplicate e&'s own fixed cover or, for
                # plain Smart mode, force the user's real first section into
                # a title-only slide).
                "has_explicit_slide_structure": has_explicit_slide_structure,
            },
        ).to_string()

    async def rollback_stream_session():
        await sql_session.rollback()

    return StreamingResponse(
        safe_sse_stream(
            inner(),
            logger=LOGGER,
            error_detail="Failed to generate presentation outlines. Please try again.",
            on_error=rollback_stream_session,
        ),
        media_type="text/event-stream",
    )
