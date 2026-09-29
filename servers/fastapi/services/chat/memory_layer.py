import json
import logging
import os
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from constants.presentation import MAX_NUMBER_OF_SLIDES
from models.image_prompt import ImagePrompt
from models.presentation_outline_model import PresentationOutlineModel, SlideOutlineModel
from models.sql.image_asset import ImageAsset
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from services.icon_finder_service import ICON_FINDER_SERVICE
from services.documents_loader import DocumentsLoader
from services.image_generation_service import ImageGenerationService
from services.mem0_presentation_memory_service import MEM0_PRESENTATION_MEMORY_SERVICE
from services.temp_file_service import TEMP_FILE_SERVICE
from utils.asset_directory_utils import (
    filesystem_image_path_to_app_data_url,
    get_images_directory,
    normalize_slide_asset_url,
)
from utils.icon_weights import DEFAULT_ICON_WEIGHT
from utils.outline_utils import get_presentation_title_from_presentation_outline
from utils.outline_limits import normalize_outline_content

LOGGER = logging.getLogger(__name__)
DEFAULT_SOURCE_DOCUMENT_CHARS = 12000
MAX_SOURCE_DOCUMENT_CHARS = 30000
# Keep URL runtime fields during validation because many slide schemas require them.
# Speaker note is handled separately and should not affect JSON-schema checks.
class PresentationChatMemoryLayer:
    """
    Memory abstraction for chat tools and context retrieval.

    This layer intentionally hides where data comes from (SQL-backed persisted state
    and mem0 retrieval) behind `get` and `search`-style methods so chat logic stays
    decoupled from storage details.
    """

    def __init__(
        self,
        sql_session: AsyncSession,
        presentation_id: uuid.UUID,
        presentation_type: str = "standard",
    ):
        self._sql_session = sql_session
        self._presentation_id = presentation_id
        self.presentation_type = (
            "smart" if presentation_type == "smart" else "standard"
        )

    async def get(self, key: str) -> Any:
        if key != "presentation_outline":
            return None

        # Prefer live slides from SQL so slide count and slide indices are always current.
        slides_result = await self._sql_session.scalars(
            select(SlideModel)
            .where(SlideModel.presentation == self._presentation_id)
            .order_by(SlideModel.index)
        )
        slides = list(slides_result)
        if slides:
            LOGGER.info(
                "Chat outline loaded from slides table (presentation_id=%s, slides=%d)",
                self._presentation_id,
                len(slides),
            )
            return {
                "source": "slides_table",
                "format": "html",
                "slide_count": len(slides),
                "slides": [
                    {
                        "slide_id": str(slide.id),
                        "index": slide.index,
                        "content": self._html_to_text(
                            slide.html_content or ""
                        )[:1200],
                        "has_html": bool((slide.html_content or "").strip()),
                    }
                    for slide in slides
                ],
            }

        presentation = await self._sql_session.get(PresentationModel, self._presentation_id)
        if not presentation or not presentation.outlines:
            LOGGER.info(
                "Chat memory miss for outline (presentation_id=%s)",
                self._presentation_id,
            )
            return None

        LOGGER.info(
            "Chat outline fallback hit from presentation.outlines (presentation_id=%s)",
            self._presentation_id,
        )
        return presentation.outlines

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Search slides directly from SQL-backed slide rows.

        Results are intentionally compact (snippet-first) to keep tool-call payloads
        small for models with limited context windows.
        """

        trimmed_query = (query or "").strip()
        if not trimmed_query:
            return []

        slides_result = await self._sql_session.scalars(
            select(SlideModel).where(SlideModel.presentation == self._presentation_id)
        )
        slides = sorted(list(slides_result), key=lambda slide: slide.index)
        if not slides:
            LOGGER.info(
                "Chat memory miss for slide search (presentation_id=%s, reason=no_slides)",
                self._presentation_id,
            )
            return []

        query_lower = trimmed_query.lower()
        query_tokens = set(re.findall(r"[a-z0-9]{2,}", query_lower))
        ranked: list[tuple[int, dict[str, Any]]] = []
        for slide in slides:
            serialized = self._serialize_slide(slide)
            searchable = serialized.lower()

            score = 0
            if query_lower in searchable:
                score += 8
            if query_tokens:
                score += sum(1 for token in query_tokens if token in searchable)
            if score <= 0:
                continue

            ranked.append(
                (
                    score,
                    {
                        "slide_id": str(slide.id),
                        "index": slide.index,
                        "slide_number": slide.index + 1,
                        "layout_id": slide.layout,
                        "snippet": self._build_snippet(serialized, query_lower),
                        "score": score,
                    },
                )
            )

        ranked.sort(key=lambda item: (-item[0], item[1]["index"]))
        results = [entry for _, entry in ranked[: max(1, limit)]]
        LOGGER.info(
            "Chat DB slide search completed (presentation_id=%s, query=%r, hits=%d)",
            self._presentation_id,
            trimmed_query,
            len(results),
        )
        return results

    async def get_slide_at_index(
        self, index: int, *, include_full_content: bool = False
    ) -> dict[str, Any] | None:
        slide = await self._sql_session.scalar(
            select(SlideModel).where(
                SlideModel.presentation == self._presentation_id,
                SlideModel.index == index,
            )
        )
        if not slide:
            LOGGER.info(
                "Chat memory miss for slide by index (presentation_id=%s, index=%d)",
                self._presentation_id,
                index,
            )
            return None

        response: dict[str, Any] = {
            "slide_id": str(slide.id),
            "index": slide.index,
            "slide_number": slide.index + 1,
            "layout_id": slide.layout,
            "content_preview": self._build_snippet(
                self._serialize_slide(slide),
                query_lower="",
                window=420,
            ),
            "speaker_note": slide.speaker_note,
        }
        html = slide.html_content or ""
        response.update(
            {
                "format": "html",
                "has_html": bool(html.strip()),
                "html_length": len(html),
                "html_text_preview": self._html_to_text(html)[:1200],
            }
        )
        if include_full_content:
            response["html"] = html
        return response

    async def get_outline(self) -> dict[str, Any]:
        presentation = await self._sql_session.get(PresentationModel, self._presentation_id)
        if not presentation:
            return {"found": False, "message": "Presentation not found."}

        # Same normalization as add/update/delete_outline, so indexes here are the ones they act on.
        slides = self._normalize_outline_slides(presentation.outlines)
        return {
            "found": True,
            "slide_count": len(slides),
            "max_slide_count": MAX_NUMBER_OF_SLIDES,
            "slides": [
                {"index": index, "slide_number": index + 1, "content": slide["content"]}
                for index, slide in enumerate(slides)
            ],
        }

    async def add_outline(
        self,
        *,
        content: str,
        index: int | None = None,
    ) -> dict[str, Any]:
        presentation = await self._sql_session.get(PresentationModel, self._presentation_id)
        if not presentation:
            return {
                "saved": False,
                "message": "Presentation not found.",
            }

        slides = self._normalize_outline_slides(presentation.outlines)
        if len(slides) >= MAX_NUMBER_OF_SLIDES:
            return {
                "saved": False,
                "message": f"Outline slide limit reached. You can have at most {MAX_NUMBER_OF_SLIDES} outlines.",
                "slide_count": len(slides),
                "max_slide_count": MAX_NUMBER_OF_SLIDES,
            }
        insert_index = len(slides) if index is None else min(max(0, index), len(slides))
        slides.insert(insert_index, {"content": normalize_outline_content(content.strip())})
        await self._save_outline_slides(presentation, slides)

        return {
            "saved": True,
            "action": "created",
            "message": f"Outline slide added at index {insert_index}.",
            "index": insert_index,
            "slide_count": len(slides),
        }

    async def update_outline(self, *, index: int, content: str) -> dict[str, Any]:
        presentation = await self._sql_session.get(PresentationModel, self._presentation_id)
        if not presentation:
            return {
                "saved": False,
                "message": "Presentation not found.",
            }

        slides = self._normalize_outline_slides(presentation.outlines)
        target_index = max(0, index)
        if target_index >= len(slides):
            return {
                "saved": False,
                "message": f"No outline slide found at index {target_index}.",
                "index": target_index,
                "slide_count": len(slides),
            }

        slides[target_index] = {"content": normalize_outline_content(content.strip())}
        await self._save_outline_slides(presentation, slides)

        return {
            "saved": True,
            "action": "updated",
            "message": f"Outline slide at index {target_index} was updated.",
            "index": target_index,
            "slide_count": len(slides),
        }

    async def delete_outline(self, *, index: int) -> dict[str, Any]:
        presentation = await self._sql_session.get(PresentationModel, self._presentation_id)
        if not presentation:
            return {
                "deleted": False,
                "message": "Presentation not found.",
            }

        slides = self._normalize_outline_slides(presentation.outlines)
        target_index = max(0, index)
        if target_index >= len(slides):
            return {
                "deleted": False,
                "message": f"No outline slide found at index {target_index}.",
                "index": target_index,
                "slide_count": len(slides),
            }

        slides.pop(target_index)
        await self._save_outline_slides(presentation, slides)

        return {
            "deleted": True,
            "action": "deleted",
            "message": f"Outline slide at index {target_index} was deleted.",
            "index": target_index,
            "slide_count": len(slides),
        }

    async def read_source_documents(
        self,
        *,
        query: str | None = None,
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        presentation = await self._sql_session.get(
            PresentationModel, self._presentation_id
        )
        if not presentation:
            return {
                "found": False,
                "message": "Presentation not found.",
                "documents": [],
            }

        char_budget = min(
            max(max_chars or DEFAULT_SOURCE_DOCUMENT_CHARS, 1000),
            MAX_SOURCE_DOCUMENT_CHARS,
        )
        source_paths = [
            path
            for path in (presentation.file_paths or [])
            if isinstance(path, str) and path.strip()
        ]

        documents: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        remaining_chars = char_budget

        for source_index, raw_path in enumerate(source_paths):
            if remaining_chars <= 0:
                break

            name = os.path.basename(raw_path) or f"Document {source_index + 1}"
            try:
                resolved_path = TEMP_FILE_SERVICE.resolve_temp_path(
                    raw_path,
                    must_exist=True,
                )
                loader = DocumentsLoader(
                    file_paths=[resolved_path],
                    presentation_language=presentation.language,
                )
                temp_dir = TEMP_FILE_SERVICE.create_temp_dir(str(uuid.uuid4()))
                await loader.load_documents(temp_dir=temp_dir)
                parsed_text = loader.documents[0] if loader.documents else ""
            except Exception as exc:
                errors.append({"name": name, "error": str(exc)})
                continue

            trimmed = self._trim_document_text(parsed_text, remaining_chars)
            if not trimmed:
                errors.append({"name": name, "error": "No text was extracted."})
                continue

            documents.append(
                {
                    "index": source_index,
                    "name": name,
                    "content": trimmed,
                    "truncated": len(parsed_text.strip()) > len(trimmed),
                }
            )
            remaining_chars -= len(trimmed)

        if documents:
            omitted_count = max(0, len(source_paths) - len(documents) - len(errors))
            return {
                "found": True,
                "source": "uploaded_files",
                "count": len(documents),
                "documents": documents,
                "errors": errors,
                "omitted_count": omitted_count,
                "message": f"Read {len(documents)} source document(s).",
            }

        fallback_query = (
            (query or "").strip()
            or "uploaded source document extracted PDF document text summary"
        )
        fallback_context = await MEM0_PRESENTATION_MEMORY_SERVICE.retrieve_context(
            self._presentation_id,
            fallback_query,
        )
        if fallback_context.strip():
            return {
                "found": True,
                "source": "presentation_memory",
                "count": 1,
                "documents": [
                    {
                        "index": 0,
                        "name": "Indexed source document context",
                        "content": self._trim_document_text(
                            fallback_context,
                            char_budget,
                        ),
                        "truncated": len(fallback_context.strip()) > char_budget,
                    }
                ],
                "errors": errors,
                "message": (
                    "Source upload files were unavailable, so indexed document "
                    "memory was returned instead."
                ),
            }

        if source_paths:
            return {
                "found": False,
                "source": "uploaded_files",
                "count": 0,
                "documents": [],
                "errors": errors,
                "message": (
                    "Source document files are recorded for this presentation, "
                    "but no readable text could be extracted."
                ),
            }

        return {
            "found": False,
            "source": "presentation",
            "count": 0,
            "documents": [],
            "errors": errors,
            "message": "No uploaded source documents are linked to this presentation.",
        }

    async def generate_image(self, prompt: str) -> str:
        image_generation_service = ImageGenerationService(get_images_directory())
        image = await image_generation_service.generate_image(ImagePrompt(prompt=prompt))

        if isinstance(image, ImageAsset):
            self._sql_session.add(image)
            await self._sql_session.commit()
            return filesystem_image_path_to_app_data_url(image.path)

        return normalize_slide_asset_url(str(image))

    async def generate_icon(self, query: str) -> str:
        icons = await ICON_FINDER_SERVICE.search_icons(
            query,
            k=1,
            weight=DEFAULT_ICON_WEIGHT,
        )
        if icons:
            return normalize_slide_asset_url(icons[0])
        return normalize_slide_asset_url("/static/icons/placeholder.svg")

    async def get_smart_presentation_context(
        self,
        *,
        include_slide_html: bool = False,
        max_html_chars_per_slide: int = 0,
    ) -> dict[str, Any]:
        presentation = await self._sql_session.get(
            PresentationModel,
            self._presentation_id,
        )
        if not presentation:
            return {"found": False, "message": "Presentation not found."}

        slides_result = await self._sql_session.scalars(
            select(SlideModel)
            .where(SlideModel.presentation == self._presentation_id)
            .order_by(SlideModel.index)
        )
        slides = list(slides_result)
        slide_rows: list[dict[str, Any]] = []
        for slide in slides:
            html = slide.html_content or ""
            row: dict[str, Any] = {
                "slide_id": str(slide.id),
                "index": slide.index,
                "slide_number": slide.index + 1,
                "title": self._smart_slide_title(html, slide.index),
                "html_length": len(html),
                "html_text_preview": self._html_to_text(html)[:1200],
            }
            if include_slide_html:
                row["html"] = (
                    html[:max_html_chars_per_slide]
                    if max_html_chars_per_slide > 0
                    else html
                )
            slide_rows.append(row)

        return {
            "found": True,
            "stage": "html_slides" if slides else "missing_html_slides",
            "presentation_id": str(presentation.id),
            "title": presentation.title,
            "language": presentation.language,
            "tone": presentation.tone,
            "verbosity": presentation.verbosity,
            "instructions": presentation.instructions,
            "fonts": presentation.fonts or {},
            "community_design_ids": presentation.community_design_ids or [],
            "outlines": presentation.outlines,
            "structure": presentation.structure,
            "slide_count": len(slides),
            "slides": slide_rows,
        }

    async def save_html_slide(
        self,
        *,
        html: str,
        index: int,
        replace_old_slide_at_index: bool,
        speaker_note: str | None = None,
    ) -> dict[str, Any]:
        from fastapi import HTTPException
        from utils.llm_calls.generate_smart_presentation import (
            normalize_smart_slide_html,
        )

        presentation = await self._sql_session.get(
            PresentationModel,
            self._presentation_id,
        )
        if not presentation:
            return {
                "saved": False,
                "message": "Presentation not found.",
                "validation_errors": [],
            }
        if presentation.generation_mode != "smart":
            return {
                "saved": False,
                "message": "Only Smart presentations can save HTML slides.",
                "validation_errors": [],
            }

        try:
            normalized_html = normalize_smart_slide_html(html)
        except HTTPException as exc:
            return {
                "saved": False,
                "message": "Smart slide HTML failed validation.",
                "validation_errors": [str(exc.detail)],
            }

        target_index = max(0, index)
        title = self._smart_slide_title(normalized_html, target_index)
        if replace_old_slide_at_index:
            slide = await self._sql_session.scalar(
                select(SlideModel).where(
                    SlideModel.presentation == self._presentation_id,
                    SlideModel.index == target_index,
                )
            )
            if not slide:
                return {
                    "saved": False,
                    "message": f"No Smart slide found at index {target_index}.",
                    "validation_errors": [],
                }
            slide.layout_group = "smart-html"
            slide.layout = "smart-html"
            slide.content = {"title": title}
            slide.html_content = normalized_html
            slide.ui = None
            if speaker_note is not None:
                slide.speaker_note = speaker_note
            self._sql_session.add(slide)
            await self._sql_session.commit()
            return {
                "saved": True,
                "action": "replaced",
                "message": f"Smart slide at index {target_index} was replaced.",
                "slide_id": str(slide.id),
                "index": target_index,
                "slide_number": target_index + 1,
            }

        slides_result = await self._sql_session.scalars(
            select(SlideModel)
            .where(SlideModel.presentation == self._presentation_id)
            .order_by(SlideModel.index)
        )
        slides = list(slides_result)
        if len(slides) >= MAX_NUMBER_OF_SLIDES:
            return {
                "saved": False,
                "message": (
                    "Slide limit reached. You can have at most "
                    f"{MAX_NUMBER_OF_SLIDES} slides."
                ),
                "validation_errors": [],
            }

        insert_index = min(target_index, len(slides))
        for slide in sorted(
            [item for item in slides if item.index >= insert_index],
            key=lambda item: item.index,
            reverse=True,
        ):
            slide.index += 1
            self._sql_session.add(slide)

        new_slide = SlideModel(
            presentation=self._presentation_id,
            layout_group="smart-html",
            layout="smart-html",
            index=insert_index,
            content={"title": title},
            html_content=normalized_html,
            speaker_note=speaker_note or "",
            ui=None,
        )
        presentation.n_slides = len(slides) + 1
        self._sql_session.add(presentation)
        self._sql_session.add(new_slide)
        await self._sql_session.commit()
        await self._sql_session.refresh(new_slide)
        return {
            "saved": True,
            "action": "created",
            "message": f"Smart slide added at index {insert_index}.",
            "slide_id": str(new_slide.id),
            "index": insert_index,
            "slide_number": insert_index + 1,
        }

    async def delete_slide(self, *, index: int) -> dict[str, Any]:
        target_index = max(0, index)
        slide = await self._sql_session.scalar(
            select(SlideModel).where(
                SlideModel.presentation == self._presentation_id,
                SlideModel.index == target_index,
            )
        )
        if not slide:
            return {
                "deleted": False,
                "message": f"No slide found at index {target_index}.",
                "index": target_index,
            }

        presentation = await self._sql_session.get(PresentationModel, self._presentation_id)
        slides_result = await self._sql_session.scalars(
            select(SlideModel)
            .where(SlideModel.presentation == self._presentation_id)
            .order_by(SlideModel.index)
        )
        slides = sorted(list(slides_result), key=lambda each: each.index)
        deleted_slide_id = str(slide.id)

        if len(slides) <= 1:
            fallback_slide = SlideModel(
                owner_id=slide.owner_id,
                presentation=self._presentation_id,
                layout_group="smart-html",
                layout="smart-html",
                index=0,
                content={"title": "Untitled slide"},
                html_content=(
                    '<section data-slide-type="content" '
                    'data-slide-title="Untitled slide" '
                    'class="relative h-[720px] w-[1280px] overflow-hidden '
                    'bg-white"><div class="flex h-full items-center '
                    'justify-center p-16"><h2 class="text-5xl font-semibold '
                    'text-slate-900">Untitled slide</h2></div></section>'
                ),
                speaker_note="",
                ui=None,
            )
            await self._sql_session.delete(slide)
            if presentation:
                presentation.n_slides = 1
                self._sql_session.add(presentation)
            self._sql_session.add(fallback_slide)
            await self._sql_session.commit()
            await self._sql_session.refresh(fallback_slide)

            return {
                "deleted": True,
                "message": "Deleted the final slide and added a blank fallback slide.",
                "deleted_slide_id": deleted_slide_id,
                "slide_id": str(fallback_slide.id),
                "index": 0,
                "slide_number": 1,
                "shifted_slide_count": 0,
                "blank_fallback": True,
            }

        await self._sql_session.delete(slide)

        remaining_slides = [
            each_slide for each_slide in slides if each_slide.id != slide.id
        ]
        shifted_count = 0
        for each_slide in remaining_slides:
            if each_slide.index <= target_index:
                continue
            each_slide.index -= 1
            self._sql_session.add(each_slide)
            shifted_count += 1

        if presentation:
            presentation.n_slides = len(remaining_slides)
            self._sql_session.add(presentation)

        await self._sql_session.commit()

        return {
            "deleted": True,
            "message": f"Slide at index {target_index} was deleted successfully.",
            "deleted_slide_id": deleted_slide_id,
            "index": target_index,
            "shifted_slide_count": shifted_count,
        }

    async def retrieve_context(self, query: str) -> str:
        context = await MEM0_PRESENTATION_MEMORY_SERVICE.retrieve_context(
            self._presentation_id,
            query,
        )
        if context:
            LOGGER.info(
                "Chat memory semantic context hit (presentation_id=%s, chars=%d)",
                self._presentation_id,
                len(context),
            )
        else:
            LOGGER.info(
                "Chat memory semantic context miss (presentation_id=%s)",
                self._presentation_id,
            )
        return context

    @staticmethod
    def _template_asset_url(value: Any) -> str | None:
        if isinstance(value, str):
            return normalize_slide_asset_url(value)
        if not isinstance(value, dict):
            return None

        fallback_url: str | None = None
        for key in (
            "data",
            "url",
            "image_url",
            "icon_url",
            "__image_url__",
            "__icon_url__",
        ):
            asset_url = value.get(key)
            if isinstance(asset_url, str) and asset_url.strip():
                normalized_url = normalize_slide_asset_url(asset_url)
                if normalized_url.strip().startswith(
                    ("http://", "https://", "/app_data/", "/static/", "data:", "blob:")
                ):
                    return normalized_url
                if fallback_url is None:
                    fallback_url = normalized_url
        return fallback_url

    @staticmethod
    def _normalize_outline_slides(outlines: Any) -> list[dict[str, str]]:
        if not isinstance(outlines, dict):
            return []

        raw_slides = outlines.get("slides")
        if not isinstance(raw_slides, list):
            return []

        slides: list[dict[str, str]] = []
        for raw_slide in raw_slides:
            raw_content: Any
            if isinstance(raw_slide, dict):
                raw_content = raw_slide.get("content", "")
            else:
                raw_content = raw_slide

            if isinstance(raw_content, str):
                content = raw_content
            elif raw_content is None:
                content = ""
            else:
                try:
                    content = json.dumps(raw_content, ensure_ascii=False)
                except Exception:
                    content = str(raw_content)

            slides.append({"content": normalize_outline_content(content)})

        return slides

    async def _save_outline_slides(
        self,
        presentation: PresentationModel,
        slides: list[dict[str, str]],
    ) -> None:
        outline_model = PresentationOutlineModel(
            slides=[SlideOutlineModel(content=slide["content"]) for slide in slides]
        )
        presentation.outlines = outline_model.model_dump(mode="json")
        presentation.n_slides = len(outline_model.slides)
        presentation.title = get_presentation_title_from_presentation_outline(
            outline_model
        )

        self._sql_session.add(presentation)
        await self._sql_session.commit()

        await MEM0_PRESENTATION_MEMORY_SERVICE.store_generated_outlines(
            presentation.id,
            presentation.outlines,
        )

    @staticmethod
    def _serialize_slide(slide: SlideModel) -> str:
        if slide.html_content:
            return (
                f"slide_index={slide.index}\nlayout_id={slide.layout}\n"
                f"{PresentationChatMemoryLayer._html_to_text(slide.html_content)}\n"
                f"{slide.speaker_note or ''}"
            )
        content_text = ""
        try:
            content_text = json.dumps(slide.content or {}, ensure_ascii=False)
        except Exception:
            content_text = str(slide.content)

        speaker_note = slide.speaker_note or ""
        return f"slide_index={slide.index}\nlayout_id={slide.layout}\n{content_text}\n{speaker_note}"

    @staticmethod
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        without_scripts = re.sub(
            r"<script\b[^>]*>.*?</script\b[^>]*>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
        return " ".join(without_tags.split())

    @staticmethod
    def _smart_slide_title(html: str, index: int) -> str:
        title_match = re.search(
            r"\bdata-slide-title\s*=\s*(?:\"([^\"]*)\"|'([^']*)')",
            html,
            flags=re.IGNORECASE,
        )
        if title_match:
            title = (title_match.group(1) or title_match.group(2) or "").strip()
            if title:
                return title[:200]

        heading_match = re.search(
            r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if heading_match:
            title = PresentationChatMemoryLayer._html_to_text(
                heading_match.group(1)
            ).strip()
            if title:
                return title[:200]
        return f"Slide {index + 1}"

    @staticmethod
    def _build_snippet(text: str, query_lower: str, window: int = 320) -> str:
        normalized = " ".join(text.split())
        if not normalized:
            return ""

        offset = normalized.lower().find(query_lower)
        if offset == -1:
            return normalized[:window]

        start = max(0, offset - window // 3)
        end = min(len(normalized), start + window)
        return normalized[start:end]

    @staticmethod
    def _trim_document_text(text: str, limit: int) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return ""
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}\n[Document content truncated]"

