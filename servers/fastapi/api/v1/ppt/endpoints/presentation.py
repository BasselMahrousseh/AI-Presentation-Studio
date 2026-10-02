import asyncio
import json
import logging
from typing import Annotated, Any, List, Literal, Optional
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlmodel import select
from constants.presentation import MAX_NUMBER_OF_SLIDES
from models.presentation_and_path import PresentationAndPath
from enums.tone import Tone
from enums.verbosity import Verbosity
from models.presentation_with_slides import (
    PresentationWithSlides,
)
from services.document_fact_dedup_service import build_deduplicated_context
from services.documents_loader import DocumentsLoader
from services.temp_file_service import TEMP_FILE_SERVICE
from utils.asset_directory_utils import filesystem_export_path_to_app_data_url
from utils.export_utils import export_presentation
from utils.llm_utils import DisconnectChecker
from models.sql.slide import SlideModel
from models.sse_response import (
    SSECompleteResponse,
    SSEResponse,
    SSEStatusResponse,
)

from services.database import get_async_session
from services.database import async_session_maker
from models.sql.presentation import PresentationModel, PresentationVersion
from utils.llm_utils import TextGenerationMetrics
from utils.sse import safe_sse_stream
from llmai import get_client
from utils.llm_calls.plan_web_search import plan_web_search
from utils.llm_config import get_llm_config
from utils.llm_provider import get_model
from utils.web_search import WebSearchMode, get_selected_web_search_provider, get_web_search_route
from utils.web_search import get_web_search_context
from api.v1.auth.context import get_current_owner_id
from utils.llm_calls.generate_smart_presentation import (
    determine_smart_slide_count,
    extract_slide_type_from_html,
    generate_smart_presentation,
    resolve_smart_slide_count,
)
from utils.smart_brand_templates import (
    EAND_FIXED_SLIDE_COUNT,
    EAND_SMART_TEMPLATE_ID,
    EAND_TITLE_SUBTITLE,
    apply_smart_brand_template,
    build_eand_thank_you_slide,
    build_eand_title_slide,
    normalize_smart_brand_colors,
    normalize_smart_template_id,
)
import uuid

logger = logging.getLogger(__name__)


PRESENTATION_ROUTER = APIRouter(prefix="/presentation", tags=["Presentation"])
def _presentation_response_data(presentation: PresentationModel) -> dict:
    data = presentation.model_dump(exclude={"layout", "structure", "theme"})
    data["type"] = (
        "smart" if presentation.generation_mode == "smart" else "standard"
    )
    return data


def _build_export_cookie_header(request: Request) -> Optional[str]:
    """Credentials the export renderer sends back to Studio (it can only carry a cookie)."""
    cookie_header = (request.headers.get("cookie") or "").strip()
    if cookie_header:
        return cookie_header
    export_cookie_header = getattr(request.state, "export_cookie_header", None)
    if isinstance(export_cookie_header, str) and export_cookie_header:
        return export_cookie_header
    return None


@PRESENTATION_ROUTER.get("/all", response_model=List[PresentationWithSlides])
async def get_all_presentations(
    include_slides: Annotated[
        bool,
        Query(
            description=(
                "Include the first slide for dashboard previews. "
                "Disable this for metadata-only presentation lists."
            )
        ),
    ] = True,
    sort_by: Annotated[
        Literal["created_at", "updated_at"],
        Query(description="Sort newest-first by creation or last-edit time."),
    ] = "created_at",
    favorites_only: Annotated[
        bool, Query(description="Only include decks marked as favourite.")
    ] = False,
    include_unfinished: Annotated[
        bool,
        Query(
            description=(
                "Also list decks whose generation is still 'in_progress' even though their first "
                "slide does not exist yet (e.g. interrupted mid-generation), returned with an empty "
                "slides list. Off by default: clients that assume slides[0] exists must opt in."
            )
        ),
    ] = False,
    sql_session: AsyncSession = Depends(get_async_session),
):
    # Every e& cover is the same red title layout, so as a dashboard thumbnail it tells decks apart
    # only by the title the card already prints. e& decks preview their first content slide
    # instead; other decks keep their cover. The index-0 join below still decides which decks
    # are listed and whether one is unfinished.
    preview_slide = aliased(SlideModel)
    preview_join_condition = (
        (preview_slide.presentation == PresentationModel.id)
        & (preview_slide.index == 1)
        & (PresentationModel.smart_template == EAND_SMART_TEMPLATE_ID)
    )
    if include_slides and include_unfinished:
        # Outer join: a deck whose first slide does not exist yet (e& decks add the cover last)
        # must still be listed while its generation is unfinished, so the user can resume or delete
        # it. Slide-less drafts (e.g. the outline step's) are filtered out below.
        query = (
            select(PresentationModel, SlideModel, preview_slide)
            .outerjoin(
                SlideModel,
                (SlideModel.presentation == PresentationModel.id) & (SlideModel.index == 0),
            )
            .outerjoin(preview_slide, preview_join_condition)
        )
    elif include_slides:
        query = (
            select(PresentationModel, SlideModel, preview_slide)
            .join(
                SlideModel,
                (SlideModel.presentation == PresentationModel.id) & (SlideModel.index == 0),
            )
            .outerjoin(preview_slide, preview_join_condition)
        )
    else:
        query = select(PresentationModel)

    # Only Smart decks are listed. "standard" rows are outline drafts, or legacy TemplateV2 decks
    # that the Workspace can no longer open; they stay in the database untouched.
    query = query.where(PresentationModel.generation_mode == "smart")
    if favorites_only:
        query = query.where(PresentationModel.is_favorite.is_(True))
    if include_slides and include_unfinished:
        query = query.where(
            or_(
                SlideModel.id.is_not(None),
                PresentationModel.generation_status == "in_progress",
            )
        )
    sort_column = (
        PresentationModel.updated_at
        if sort_by == "updated_at"
        else PresentationModel.created_at
    )
    query = query.order_by(sort_column.desc())

    results = await sql_session.execute(query)
    if not include_slides:
        return [
            PresentationWithSlides(
                **_presentation_response_data(presentation),
                slides=[],
            )
            for presentation in results.scalars().all()
        ]

    rows = results.all()
    presentations_with_slides = []
    for presentation, first_slide, content_slide in rows:
        # A deck without its first slide stays slide-less (the UI shows it as unfinished), even
        # when a later slide already exists: e& generation adds the cover last.
        if first_slide is None:
            slides = []
        else:
            slides = [content_slide if content_slide is not None else first_slide]
        presentations_with_slides.append(
            PresentationWithSlides(
                **_presentation_response_data(presentation),
                slides=slides,
            )
        )
    return presentations_with_slides


@PRESENTATION_ROUTER.get("/{id}", response_model=PresentationWithSlides)
async def get_presentation(
    id: uuid.UUID,
    request: Request,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(404, "Presentation not found")
    slides_result = await sql_session.scalars(
        select(SlideModel)
        .where(SlideModel.presentation == id)
        .order_by(SlideModel.index)
    )
    slides = list(slides_result)
    return PresentationWithSlides(
        **_presentation_response_data(presentation),
        slides=slides,
    )


class FavoriteUpdate(BaseModel):
    is_favorite: bool


@PRESENTATION_ROUTER.patch("/{id}/favorite")
async def set_presentation_favorite(
    id: uuid.UUID,
    body: FavoriteUpdate,
    sql_session: AsyncSession = Depends(get_async_session),
):
    # The owner scope on ORM selects makes another user's deck a plain 404 here.
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(404, "Presentation not found")

    # Core UPDATE with updated_at pinned to itself: favouriting is not an edit, and the
    # column's onupdate hook would otherwise bump "last edited" and reorder the dashboard.
    await sql_session.execute(
        update(PresentationModel)
        .where(PresentationModel.id == id)
        .values(
            is_favorite=body.is_favorite,
            updated_at=PresentationModel.updated_at,
        )
    )
    await sql_session.commit()
    return {"id": id, "is_favorite": body.is_favorite}


@PRESENTATION_ROUTER.delete("/{id}", status_code=204)
async def delete_presentation(
    id: uuid.UUID, sql_session: AsyncSession = Depends(get_async_session)
):
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(404, "Presentation not found")

    await sql_session.delete(presentation)
    await sql_session.commit()


@PRESENTATION_ROUTER.post("/{id}/duplicate", response_model=PresentationWithSlides)
async def duplicate_presentation(
    id: uuid.UUID, sql_session: AsyncSession = Depends(get_async_session)
):
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(404, "Presentation not found")

    slides = list(
        await sql_session.scalars(
            select(SlideModel)
            .where(SlideModel.presentation == id)
            .order_by(SlideModel.index)
        )
    )
    new_presentation = presentation.get_new_presentation()
    if new_presentation.title:
        new_presentation.title = f"{new_presentation.title} (Copy)"
    new_slides = [slide.get_new_slide(new_presentation.id) for slide in slides]

    sql_session.add(new_presentation)
    sql_session.add_all(new_slides)
    await sql_session.commit()
    await sql_session.refresh(new_presentation)

    return PresentationWithSlides(
        **_presentation_response_data(new_presentation),
        slides=new_slides,
    )


def _existing_source_file_paths(file_paths: Optional[List[str]]) -> List[str]:
    """Resolve stored source file paths, dropping any that no longer exist
    (TempFileService wipes the temp dir on every backend start)."""
    existing: List[str] = []
    for file_path in file_paths or []:
        try:
            existing.append(TEMP_FILE_SERVICE.resolve_temp_path(file_path, must_exist=True))
        except HTTPException:
            logger.warning("[smart-workflow] source file unavailable, skipping: %s", file_path)
    return existing


@PRESENTATION_ROUTER.post("/create", response_model=PresentationModel)
async def create_presentation(
    content: Annotated[str, Body()],
    n_slides: Annotated[Optional[int], Body()] = None,
    language: Annotated[Optional[str], Body()] = None,
    file_paths: Annotated[Optional[List[str]], Body()] = None,
    tone: Annotated[Tone, Body()] = Tone.DEFAULT,
    verbosity: Annotated[Verbosity, Body()] = Verbosity.STANDARD,
    instructions: Annotated[Optional[str], Body()] = None,
    include_table_of_contents: Annotated[bool, Body()] = False,
    include_title_slide: Annotated[bool, Body()] = True,
    # Legacy on/off switch, still accepted: true = "always", false = "off".
    web_search: Annotated[Optional[bool], Body()] = None,
    # "auto" (default) lets a model decide per generation step whether to search.
    web_search_mode: Annotated[Optional[WebSearchMode], Body()] = None,
    generation_mode: Annotated[Literal["standard", "smart"], Body()] = "standard",
    smart_template: Annotated[Optional[str], Body()] = None,
    smart_brand_colors: Annotated[Optional[List[str]], Body()] = None,
    source_presentation_id: Annotated[Optional[uuid.UUID], Body()] = None,
    sql_session: AsyncSession = Depends(get_async_session),
):

    if n_slides is not None and n_slides < 1:
        raise HTTPException(
            status_code=400,
            detail="Number of slides must be greater than 0",
        )

    # Clamp rather than reject: Workspace chat offers pass the count the user
    # typed (plus fixed e& slides), and the outline step caps it the same way.
    if n_slides is not None and n_slides > MAX_NUMBER_OF_SLIDES:
        n_slides = MAX_NUMBER_OF_SLIDES

    if include_table_of_contents and n_slides is not None and n_slides < 3:
        raise HTTPException(
            status_code=400,
            detail="Number of slides cannot be less than 3 if table of contents is included",
    )

    normalized_smart_template = normalize_smart_template_id(smart_template)
    normalized_smart_brand_colors = normalize_smart_brand_colors(smart_brand_colors)
    if generation_mode != "smart" and normalized_smart_template:
        raise HTTPException(
            status_code=400,
            detail="Smart brand templates are available only in Smart mode",
        )
    if normalized_smart_brand_colors and generation_mode != "smart":
        raise HTTPException(
            status_code=400,
            detail="Custom brand colors are available only in Smart mode",
        )
    if normalized_smart_brand_colors and normalized_smart_template == EAND_SMART_TEMPLATE_ID:
        # The e& palette is fixed: a reference deck's colors only restyle an
        # unbranded (Standard) Smart deck. Dropped rather than rejected so a
        # client still sending them for e& can't block deck creation.
        logger.info("[smart-workflow] ignoring custom brand colors for the e& template")
        normalized_smart_brand_colors = None
    if generation_mode == "smart" and not (
        content.strip() or file_paths
    ):
        raise HTTPException(
            status_code=400,
            detail="A prompt or document is required",
        )
    # Owner-scoped get: another user's presentation is indistinguishable from a missing one.
    source_presentation = None
    if source_presentation_id is not None:
        source_presentation = await sql_session.get(
            PresentationModel, source_presentation_id
        )
        if not source_presentation:
            raise HTTPException(404, "Source presentation not found")

    if web_search_mode is not None:
        resolved_web_search_mode: WebSearchMode = web_search_mode
    elif web_search is not None:
        resolved_web_search_mode = "always" if web_search else "off"
    elif source_presentation is not None:
        # A Smart deck built from an approved outline keeps the outline's setting.
        resolved_web_search_mode = source_presentation.effective_web_search_mode
    else:
        resolved_web_search_mode = "auto"

    presentation_id = uuid.uuid4()
    language_to_store = (language or "").strip()
    if file_paths:
        validated_file_paths = TEMP_FILE_SERVICE.resolve_existing_temp_paths(file_paths)
    elif source_presentation is not None and source_presentation.file_paths:
        # A deck built from an approved outline (the outline page's Smart/e&
        # buttons) must see the same source documents the outline was grounded
        # in - otherwise every figure not condensed into an outline bullet is
        # lost. Inherited files may have been removed since (the temp dir is
        # wiped on every backend start), so skip missing ones instead of
        # failing the whole deck with a 404.
        validated_file_paths = _existing_source_file_paths(
            source_presentation.file_paths
        ) or None
    else:
        validated_file_paths = None
    # DB schema stores an int; 0 is used as internal marker for auto slide count.
    n_slides_to_store = n_slides if n_slides is not None else 0

    presentation = PresentationModel(
        id=presentation_id,
        version=PresentationVersion.V2_STANDARD,
        content=content,
        # A deck built from an approved outline starts with the outline's title, so the dashboard
        # can name it before generation finishes (its content is the internal outline prompt).
        # The generated deck title replaces it on completion.
        title=source_presentation.title if source_presentation is not None else None,
        n_slides=n_slides_to_store,
        language=language_to_store,
        file_paths=validated_file_paths,
        tone=tone.value,
        verbosity=verbosity.value,
        instructions=instructions,
        include_table_of_contents=include_table_of_contents,
        include_title_slide=include_title_slide,
        web_search=resolved_web_search_mode != "off",
        web_search_mode=resolved_web_search_mode,
        generation_mode=generation_mode,
        smart_template=normalized_smart_template,
        smart_brand_colors=normalized_smart_brand_colors,
        source_presentation_id=source_presentation_id,
    )

    sql_session.add(presentation)
    await sql_session.commit()

    logger.info(
        "[smart-workflow] created presentation_id=%s mode=%s requested_slides=%s stored_slides=%s files=%s smart_template=%s",
        presentation.id, generation_mode, n_slides, presentation.n_slides,
        len(validated_file_paths or []),
        normalized_smart_template or "none",
    )

    search_route, actual_search_provider = get_web_search_route()
    logger.info(
        "Created presentation: id=%s web_search_mode=%s selected_web_search_provider=%s "
        "web_search_route=%s actual_web_search_provider=%s",
        presentation_id,
        resolved_web_search_mode,
        get_selected_web_search_provider().value,
        search_route,
        (
            actual_search_provider.value
            if actual_search_provider
            else ("model-native" if search_route == "native" else "none")
        ),
    )

    return presentation


async def _stream_smart_presentation(
    presentation: PresentationModel,
    disconnect_checker: Optional[DisconnectChecker] = None,
) -> StreamingResponse:
    presentation_id = presentation.id
    logger.info(
        "[smart-workflow] smart_stream_start presentation_id=%s stored_slides=%s files=%s web_search_mode=%s",
        presentation_id, presentation.n_slides, len(presentation.file_paths or []),
        presentation.effective_web_search_mode,
    )

    async def inner():
        # Scoped to just this query: a Smart generation runs for
        # minutes (LLM calls, Puppeteer layout checks), and holding one
        # DB session/connection open for that whole span would exhaust
        # the connection pool under concurrent generations on
        # Postgres/MySQL. See CLAUDE.md's DB-transaction-lifetime note.
        async with async_session_maker() as sql_session:
            existing_slides = list(
                await sql_session.scalars(
                    select(SlideModel)
                    .where(SlideModel.presentation == presentation_id)
                    .order_by(SlideModel.index)
                )
            )
        # A presentation that was still "in_progress" when it was last
        # touched (e.g. the client disconnected/reloaded mid-generation -
        # see CLAUDE.md's "Next.js exited cleanly" entry) resumes
        # generation below instead of replaying a false-complete deck;
        # only a genuinely-finished presentation's existing slides
        # short-circuit generation entirely, as before.
        is_resuming_generation = (
            bool(existing_slides)
            and presentation.generation_status == "in_progress"
        )
        if existing_slides and not is_resuming_generation:
            logger.info("[smart-workflow] smart_stream_reusing_existing presentation_id=%s slides=%s", presentation_id, len(existing_slides))
            for slide in existing_slides:
                yield SSEResponse(
                    event="response",
                    data=json.dumps(
                        {
                            "type": "slide_html",
                            "index": slide.index,
                            "slide_id": str(slide.id),
                            "html": slide.html_content,
                            "slide": slide.model_dump(mode="json"),
                            "total_slides": len(existing_slides),
                        }
                    ),
                ).to_string()
            response = PresentationWithSlides(
                **_presentation_response_data(presentation),
                slides=existing_slides,
            )
            yield SSECompleteResponse(
                key="presentation",
                value=response.model_dump(mode="json"),
            ).to_string()
            return

        if is_resuming_generation:
            logger.info("[smart-workflow] smart_stream_resuming presentation_id=%s already_persisted_slides=%s", presentation_id, len(existing_slides))

        yield SSEStatusResponse(status="Preparing Smart presentation").to_string()

        source_parts: list[str] = []
        # Source files live in the temp dir, which is wiped on every backend
        # start - a restart between creating this deck and streaming it (or
        # resuming an interrupted run) must degrade to outline-only generation,
        # not a 404 mid-stream.
        source_file_paths = _existing_source_file_paths(presentation.file_paths)
        if presentation.file_paths and len(source_file_paths) < len(presentation.file_paths):
            yield SSEStatusResponse(
                status="Some source documents are no longer available"
            ).to_string()
        if source_file_paths:
            yield SSEStatusResponse(status="Reading source documents").to_string()
            documents_loader = DocumentsLoader(
                file_paths=source_file_paths,
                presentation_language=presentation.language,
            )
            await documents_loader.load_documents(
                TEMP_FILE_SERVICE.create_temp_dir()
            )
            document_context = await build_deduplicated_context(
                source_file_paths,
                documents_loader.documents,
                documents_loader.structured_pptx_data,
                disconnect_checker=disconnect_checker,
            )
            if document_context:
                source_parts.append(document_context)
            logger.info("[smart-workflow] smart_documents_loaded presentation_id=%s documents=%s", presentation_id, len(documents_loader.documents))

        web_search_mode = presentation.effective_web_search_mode
        if web_search_mode != "off":
            if web_search_mode == "auto":
                yield SSEStatusResponse(
                    status="Checking whether this topic needs web research"
                ).to_string()
            search_plan = await plan_web_search(
                get_client(config=get_llm_config()),
                get_model(),
                web_search_mode,
                presentation.content,
                presentation.instructions,
                disconnect_checker=disconnect_checker,
            )
            logger.info(
                "[smart-workflow] smart_web_search_plan presentation_id=%s mode=%s search=%s reason=%s queries=%r",
                presentation_id, web_search_mode, search_plan.search, search_plan.reason, search_plan.queries,
            )
            if search_plan.search and search_plan.queries:
                yield SSEStatusResponse(status="Searching the web").to_string()
                search_context = await get_web_search_context(list(search_plan.queries))
                if search_context:
                    source_parts.append(search_context)
                logger.info("[smart-workflow] smart_web_search_complete presentation_id=%s result_chars=%s", presentation_id, len(search_context or ""))

        source_context = "\n\n".join(source_parts)
        if len(source_context) > 90_000:
            source_context = source_context[:90_000]

        is_eand_template = presentation.smart_template == EAND_SMART_TEMPLATE_ID
        fixed_slide_count = EAND_FIXED_SLIDE_COUNT if is_eand_template else 0
        if is_resuming_generation:
            # presentation.n_slides already holds the resolved TOTAL
            # (content + fixed) written by the interrupted run's own early
            # commit below - resolve_smart_slide_count()/
            # determine_smart_slide_count() both expect a raw, not-yet-
            # resolved user-requested content count, so re-running either
            # here against an already-resolved total would double-apply
            # the resolution and desync indices from what's already
            # streamed and persisted.
            slide_count = presentation.n_slides
            generated_slide_count = slide_count - fixed_slide_count
        elif presentation.n_slides > 0:
            # For e& decks, a user-specified count means content slides only —
            # the fixed cover/thank-you slides are added on top below.
            generated_slide_count = resolve_smart_slide_count(
                presentation.n_slides, fixed_slide_count=fixed_slide_count
            )
            slide_count = generated_slide_count + fixed_slide_count
        else:
            yield SSEStatusResponse(
                status="Choosing the right number of slides"
            ).to_string()
            generated_slide_count = await determine_smart_slide_count(
                content=presentation.content,
                instructions=presentation.instructions,
                source_context=source_context,
                include_title_slide=presentation.include_title_slide,
                include_table_of_contents=presentation.include_table_of_contents,
                minimum_slide_count=1,
                fixed_slide_count=fixed_slide_count,
            )
            slide_count = generated_slide_count + fixed_slide_count

        if not is_resuming_generation:
            presentation.n_slides = slide_count
            presentation.fonts = {
                "Inter": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
            }
            logger.info("[smart-workflow] smart_generation_ready presentation_id=%s resolved_slides=%s generated_content_slides=%s source_context_chars=%s fonts=%s", presentation_id, slide_count, generated_slide_count, len(source_context), list(presentation.fonts.keys()))
            # Committed immediately, not just in the final block at the end
            # of this function: a client reconnecting mid-generation needs
            # the real target n_slides right away - an auto-slide-count
            # Smart deck would otherwise still read n_slides=0 in the DB
            # for the entire generation - and PresentationPage.tsx's
            # blank-fallback guard on the frontend treats n_slides==0 as
            # its signal that an empty slide list is a genuinely fresh
            # presentation rather than one still streaming.
            async with async_session_maker() as sql_session:
                sql_session.add(presentation)
                presentation.generation_status = "in_progress"
                await sql_session.commit()

        yield SSEResponse(
            event="response",
            data=json.dumps(
                {
                    "type": "fonts",
                    "fonts": presentation.fonts,
                    "total_slides": slide_count,
                    # Slides the model actually generates. For
                    # e& this excludes the fixed cover/thank-you
                    # slides, which are spliced in after
                    # generation rather than streamed - so
                    # progress reads "slide 4 of 10", not "of 12".
                    "generated_slide_count": generated_slide_count,
                }
            ),
        ).to_string()
        yield SSEStatusResponse(
            status="Designing the complete presentation"
        ).to_string()
        streamed_slides: dict[int, SlideModel] = {}
        if is_resuming_generation:
            for slide in existing_slides:
                streamed_slides[slide.index] = slide
                yield SSEResponse(
                    event="response",
                    data=json.dumps(
                        {
                            "type": "slide_html",
                            "index": slide.index,
                            "slide_id": str(slide.id),
                            "html": slide.html_content,
                            "slide": slide.model_dump(mode="json"),
                            "total_slides": slide_count,
                            "generated_slide_count": generated_slide_count,
                        }
                    ),
                ).to_string()
        generation_events: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def emit_slide(index: int, slide: dict[str, str]) -> None:
            if index < 0 or index >= generated_slide_count:
                return
            persisted_index = index + 1 if is_eand_template else index
            rendered_html = apply_smart_brand_template(
                presentation.smart_template, slide["html"]
            )
            streamed_slide = streamed_slides.get(persisted_index)
            if streamed_slide is None:
                streamed_slide = SlideModel(
                    presentation=presentation_id,
                    layout_group="smart-html",
                    layout="smart-html",
                    index=persisted_index,
                    content={"title": slide["title"]},
                    html_content=rendered_html,
                    speaker_note="",
                )
                streamed_slides[persisted_index] = streamed_slide
            else:
                streamed_slide.content = {"title": slide["title"]}
                streamed_slide.html_content = rendered_html
                streamed_slide.speaker_note = ""
            logger.info("[smart-workflow] smart_slide_emitted presentation_id=%s index=%s title=%r html_chars=%s", presentation_id, persisted_index, slide["title"], len(slide["html"]))
            # Persisted as soon as it's accepted, not just at the very end -
            # this is what lets a disconnect mid-generation resume instead
            # of losing everything already generated (see the
            # generation_status handling above). Safe even though this
            # same object is re-added in the final commit block below:
            # that block always deletes every existing slide row for this
            # presentation first, so there's no primary-key collision
            # regardless of what was already persisted here.
            async with async_session_maker() as sql_session:
                await sql_session.merge(streamed_slide)
                await sql_session.commit()
            await generation_events.put(("slide", streamed_slide))

        async def emit_metrics(metrics: TextGenerationMetrics) -> None:
            logger.info("[smart-workflow] smart_metrics presentation_id=%s input_tokens=%s output_tokens=%s duration_seconds=%.2f", presentation_id, metrics.input_tokens, metrics.output_tokens, metrics.duration_seconds)
            await generation_events.put(("metrics", metrics))

        seed_accepted_slides: list[dict[str, str]] | None = None
        if is_resuming_generation:
            # Seeds the retry loop's own accepted_slides so generation
            # resumes after the last already-persisted content slide
            # instead of restarting from slide 1. Uses the persisted
            # (brand-templated) html as continuity context rather than the
            # model's original raw output, which isn't stored separately -
            # an accepted, minor fidelity gap for e& decks specifically
            # (their brand chrome is spliced in before this point), not a
            # correctness issue: this text is only ever used as "already
            # accepted" prompt continuity, never re-validated.
            seed_accepted_slides = [
                {
                    "title": (slide.content or {}).get("title", ""),
                    "html": slide.html_content,
                    "speaker_note": slide.speaker_note or "",
                    # completed_slides entries need this - see
                    # extract_slide_type_from_html's own docstring for why
                    # it isn't just read off the SlideModel directly.
                    "slide_type": extract_slide_type_from_html(slide.html_content),
                }
                for slide in sorted(streamed_slides.values(), key=lambda s: s.index)
                if not is_eand_template or slide.index > 0
            ]
        generation_task = asyncio.create_task(
            generate_smart_presentation(
                content=presentation.content,
                n_slides=generated_slide_count,
                language=presentation.language,
                tone=presentation.tone,
                verbosity=presentation.verbosity,
                instructions=presentation.instructions,
                # e& provides its own fixed title slide outside the model output.
                include_title_slide=(
                    False if is_eand_template else presentation.include_title_slide
                ),
                include_table_of_contents=presentation.include_table_of_contents,
                source_context=source_context,
                fonts=presentation.fonts,
                on_slide=emit_slide,
                on_metrics=emit_metrics,
                smart_template=presentation.smart_template,
                smart_brand_colors=presentation.smart_brand_colors,
                seed_accepted_slides=seed_accepted_slides,
            )
        )

        try:
            while not generation_task.done() or not generation_events.empty():
                try:
                    event_type, event_value = await asyncio.wait_for(
                        generation_events.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue
                if event_type == "metrics":
                    metrics = event_value
                    if not isinstance(metrics, TextGenerationMetrics):
                        raise TypeError("Invalid Smart generation metrics event")
                    yield SSEResponse(
                        event="response",
                        data=json.dumps(
                            {"type": "generation_metrics", **metrics.to_dict()}
                        ),
                    ).to_string()
                    continue
                streamed_slide = event_value
                if not isinstance(streamed_slide, SlideModel):
                    raise TypeError("Invalid Smart slide event")
                yield SSEResponse(
                    event="response",
                    data=json.dumps(
                        {
                            "type": "slide_html",
                            "index": streamed_slide.index,
                            "slide_id": str(streamed_slide.id),
                            "html": streamed_slide.html_content,
                            "slide": streamed_slide.model_dump(mode="json"),
                            "total_slides": slide_count,
                            # Slides the model actually generates. For
                            # e& this excludes the fixed cover/thank-you
                            # slides, which are spliced in after
                            # generation rather than streamed - so
                            # progress reads "slide 4 of 10", not "of 12".
                            "generated_slide_count": generated_slide_count,
                        }
                    ),
                ).to_string()
            deck = await generation_task
            logger.info("[smart-workflow] smart_llm_complete presentation_id=%s deck_title=%r slides=%s", presentation_id, deck["title"], len(deck["slides"]))
        finally:
            if not generation_task.done():
                generation_task.cancel()
                await asyncio.gather(generation_task, return_exceptions=True)

        presentation.title = deck["title"]
        slides: list[SlideModel] = []

        if is_eand_template:
            title_slide = SlideModel(
                presentation=presentation_id,
                layout_group="smart-html",
                layout="smart-html",
                index=0,
                content={"title": deck["title"]},
                html_content=build_eand_title_slide(
                    deck["title"], EAND_TITLE_SUBTITLE
                ),
                speaker_note="",
            )
            slides.append(title_slide)
            yield SSEResponse(
                event="response",
                data=json.dumps(
                    {
                        "type": "slide_html",
                        "index": title_slide.index,
                        "slide_id": str(title_slide.id),
                        "html": title_slide.html_content,
                        "slide": title_slide.model_dump(mode="json"),
                        "total_slides": slide_count,
                        # Slides the model actually generates. For
                        # e& this excludes the fixed cover/thank-you
                        # slides, which are spliced in after
                        # generation rather than streamed - so
                        # progress reads "slide 4 of 10", not "of 12".
                        "generated_slide_count": generated_slide_count,
                    }
                ),
            ).to_string()

        for index, slide in enumerate(deck["slides"]):
            rendered_html = apply_smart_brand_template(
                presentation.smart_template, slide["html"]
            )
            persisted_index = index + 1 if is_eand_template else index
            final_slide = streamed_slides.get(persisted_index)
            if final_slide is None:
                final_slide = SlideModel(
                    presentation=presentation_id,
                    layout_group="smart-html",
                    layout="smart-html",
                    index=persisted_index,
                    content={"title": slide["title"]},
                    html_content=rendered_html,
                    speaker_note="",
                )
                yield SSEResponse(
                    event="response",
                    data=json.dumps(
                        {
                            "type": "slide_html",
                            "index": persisted_index,
                            "slide_id": str(final_slide.id),
                            "html": final_slide.html_content,
                            "slide": final_slide.model_dump(mode="json"),
                            "total_slides": slide_count,
                            # Slides the model actually generates. For
                            # e& this excludes the fixed cover/thank-you
                            # slides, which are spliced in after
                            # generation rather than streamed - so
                            # progress reads "slide 4 of 10", not "of 12".
                            "generated_slide_count": generated_slide_count,
                        }
                    ),
                ).to_string()
            else:
                final_slide.content = {"title": slide["title"]}
                final_slide.html_content = rendered_html
                final_slide.speaker_note = ""
            slides.append(final_slide)

        if is_eand_template:
            thank_you_slide = SlideModel(
                presentation=presentation_id,
                layout_group="smart-html",
                layout="smart-html",
                index=slide_count - 1,
                content={"title": "Thank you"},
                html_content=build_eand_thank_you_slide(),
                speaker_note="",
            )
            slides.append(thank_you_slide)
            yield SSEResponse(
                event="response",
                data=json.dumps(
                    {
                        "type": "slide_html",
                        "index": thank_you_slide.index,
                        "slide_id": str(thank_you_slide.id),
                        "html": thank_you_slide.html_content,
                        "slide": thank_you_slide.model_dump(mode="json"),
                        "total_slides": slide_count,
                        # Slides the model actually generates. For
                        # e& this excludes the fixed cover/thank-you
                        # slides, which are spliced in after
                        # generation rather than streamed - so
                        # progress reads "slide 4 of 10", not "of 12".
                        "generated_slide_count": generated_slide_count,
                    }
                ),
            ).to_string()

        # Opened fresh here, right before the actual write - the LLM
        # generation above never touches the DB, so there is nothing to
        # hold a connection open for until this point.
        async with async_session_maker() as sql_session:
            await sql_session.execute(
                delete(SlideModel).where(
                    SlideModel.presentation == presentation_id,
                    SlideModel.owner_id == get_current_owner_id(),
                )
            )
            sql_session.add(presentation)
            presentation.generation_status = "completed"
            presentation.mark_deck_generated()
            sql_session.add_all(slides)
            await sql_session.commit()
        logger.info("[smart-workflow] smart_persisted presentation_id=%s slides=%s", presentation_id, len(slides))

        response = PresentationWithSlides(
            **_presentation_response_data(presentation),
            slides=slides,
        )
        yield SSECompleteResponse(
            key="presentation",
            value=response.model_dump(mode="json"),
        ).to_string()

    return StreamingResponse(
        safe_sse_stream(
            inner(),
            logger=logger,
            error_detail="Failed to generate the Smart presentation. Please try again.",
        ),
        media_type="text/event-stream",
    )


@PRESENTATION_ROUTER.get("/stream/{id}", response_model=PresentationWithSlides)
async def stream_presentation(id: uuid.UUID, request: Request):
    # This request can run for several minutes (Smart mode especially:
    # per-slide LLM calls plus Puppeteer layout-check renders). Fetching
    # `presentation` through a dependency-injected session that FastAPI
    # only closes once the whole StreamingResponse finishes would hold a
    # pooled DB connection checked out for that entire span, even though
    # actual DB reads/writes only happen at the very start and very end.
    # On Postgres/MySQL (bounded connection pool, unlike SQLite) enough
    # concurrent generations would exhaust the pool and start timing out
    # unrelated requests. Instead, each unit of DB work below opens and
    # closes its own short-lived session.
    async with async_session_maker() as sql_session:
        presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")
    logger.info("[smart-workflow] stream_requested presentation_id=%s mode=%s stored_slides=%s", id, presentation.generation_mode, presentation.n_slides)
    if presentation.generation_mode != "smart":
        # Only Smart decks are generated. A "standard" row is the outline step's draft: the
        # Workspace turns its approved outline into a new Smart deck via /create.
        raise HTTPException(
            status_code=400,
            detail="Only Smart presentations can be generated",
        )
    return await _stream_smart_presentation(
        presentation, disconnect_checker=request.is_disconnected
    )


@PRESENTATION_ROUTER.patch("/update", response_model=PresentationWithSlides)
async def update_presentation(
    id: Annotated[uuid.UUID, Body()],
    n_slides: Annotated[Optional[int], Body()] = None,
    title: Annotated[Optional[str], Body()] = None,
    theme: Annotated[Optional[dict], Body()] = None,
    slides: Annotated[Optional[List[SlideModel]], Body()] = None,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    presentation_update_dict = {}
    if n_slides is not None:
        if n_slides < 1:
            raise HTTPException(
                status_code=400,
                detail="Number of slides must be greater than 0",
            )
        if n_slides > MAX_NUMBER_OF_SLIDES:
            raise HTTPException(
                status_code=400,
                detail=f"Number of slides cannot be greater than {MAX_NUMBER_OF_SLIDES}",
            )
        presentation_update_dict["n_slides"] = n_slides
    if title:
        presentation_update_dict["title"] = title
    if theme or theme is None:
        presentation_update_dict["theme"] = theme

    if presentation_update_dict:
        presentation.sqlmodel_update(presentation_update_dict)
    if slides:
        if len(slides) > MAX_NUMBER_OF_SLIDES:
            raise HTTPException(
                status_code=400,
                detail=f"Number of slides cannot be greater than {MAX_NUMBER_OF_SLIDES}",
            )
        # Just to make sure id is UUID
        for slide in slides:
            slide.presentation = uuid.UUID(slide.presentation)
            slide.id = uuid.UUID(slide.id)

        await sql_session.execute(
            delete(SlideModel).where(
                SlideModel.presentation == presentation.id,
                SlideModel.owner_id == get_current_owner_id(),
            )
        )
        sql_session.add_all(slides)

    await sql_session.commit()

    response_slides = slides or []
    return PresentationWithSlides(
        **_presentation_response_data(presentation),
        slides=response_slides,
    )


@PRESENTATION_ROUTER.patch("/slide_update", response_model=SlideModel)
async def update_presentation_slide(
    slide: Annotated[SlideModel, Body(embed=True)],
    sql_session: AsyncSession = Depends(get_async_session),
):
    try:
        slide_id = uuid.UUID(str(slide.id))
        presentation_id = uuid.UUID(str(slide.presentation))
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Slide and presentation IDs must be valid UUIDs",
        ) from exc

    stored_slide = await sql_session.get(SlideModel, slide_id)
    if not stored_slide:
        raise HTTPException(status_code=404, detail="Slide not found")

    if stored_slide.presentation != presentation_id:
        raise HTTPException(
            status_code=400,
            detail="Slide does not belong to the supplied presentation",
        )

    stored_slide.sqlmodel_update(
        slide.model_dump(
            exclude={"id", "presentation", "index"},
        )
    )
    sql_session.add(stored_slide)
    await sql_session.commit()
    await sql_session.refresh(stored_slide)
    return stored_slide



class ExportPresentationRequest(BaseModel):
    export_as: Literal["pptx", "pdf"]


@PRESENTATION_ROUTER.post("/{id}/export", response_model=PresentationAndPath)
async def export_existing_presentation(
    id: uuid.UUID,
    data: Annotated[ExportPresentationRequest, Body()],
    request_http: Request,
    sql_session: AsyncSession = Depends(get_async_session),
):
    """
    Exports a presentation's already-persisted content (no generation/edit step) — unlike
    /edit and /derive, which always generate or mutate content before exporting. Renders the
    same /pdf-maker page those two already point at, via the same export_presentation() service.
    """
    # The owner scope on ORM selects makes another user's deck a plain 404 here.
    presentation = await sql_session.get(PresentationModel, id)
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    presentation_and_path = await export_presentation(
        presentation.id,
        presentation.title or str(uuid.uuid4()),
        data.export_as,
        cookie_header=_build_export_cookie_header(request_http),
    )

    return PresentationAndPath(
        presentation_id=presentation_and_path.presentation_id,
        path=filesystem_export_path_to_app_data_url(presentation_and_path.path),
    )
