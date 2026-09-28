import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from services.database import get_async_session
from services.mem0_presentation_memory_service import (
    MEM0_PRESENTATION_MEMORY_SERVICE,
)
from utils.llm_calls.edit_slide_html import get_edited_slide_html
from utils.llm_calls.generate_smart_presentation import (
    _check_smart_slide_layout,
    _slide_html_scaled_to_fit,
)
from utils.smart_brand_templates import EAND_SMART_TEMPLATE_ID


SLIDE_ROUTER = APIRouter(prefix="/slide", tags=["Slide"])
LOGGER = logging.getLogger(__name__)


@SLIDE_ROUTER.post("/edit-html", response_model=SlideModel)
async def edit_slide_html(
    id: Annotated[uuid.UUID, Body()],
    prompt: Annotated[str, Body()],
    html: Annotated[Optional[str], Body()] = None,
    sql_session: AsyncSession = Depends(get_async_session),
):
    slide = await sql_session.get(SlideModel, id)
    if not slide:
        raise HTTPException(status_code=404, detail="Slide not found")

    presentation = await sql_session.get(PresentationModel, slide.presentation)
    if not presentation:
        raise HTTPException(status_code=404, detail="Presentation not found")

    html_to_edit = html or slide.html_content
    if not html_to_edit:
        raise HTTPException(status_code=400, detail="No HTML to edit")

    memory_context = await MEM0_PRESENTATION_MEMORY_SERVICE.retrieve_context(
        presentation.id,
        prompt,
    )

    edited_slide_html = await get_edited_slide_html(
        prompt,
        html_to_edit,
        memory_context,
    )

    # Full-deck generation runs every edited slide through this same
    # render-based layout check (see generate_smart_presentation.py's
    # _check_smart_slide_layout); a single-slide edit used to skip it
    # entirely, so an edit could silently reintroduce a canvas/footer
    # overflow the initial generation had already avoided (e.g. content
    # sliding down into the reserved e& footer band and visibly touching the
    # fixed logo). Mirror the same "scale slightly-too-large content to fit,
    # else reject" behavior here rather than saving unchecked.
    fit_scale = await _check_smart_slide_layout(
        edited_slide_html,
        check_eand_footer=presentation.smart_template == EAND_SMART_TEMPLATE_ID,
    )
    if fit_scale is not None:
        edited_slide_html = _slide_html_scaled_to_fit(edited_slide_html, fit_scale)

    # Always assign a new unique id to the slide
    # This is to ensure that the nextjs can track slide updates
    slide.id = uuid.uuid4()

    sql_session.add(slide)
    slide.html_content = edited_slide_html
    await sql_session.commit()

    await MEM0_PRESENTATION_MEMORY_SERVICE.store_slide_edit(
        presentation_id=presentation.id,
        slide_index=slide.index,
        edit_prompt=prompt,
        edited_slide_content=edited_slide_html,
    )

    return slide
