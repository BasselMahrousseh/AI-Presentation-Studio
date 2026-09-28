import json
import logging
import re
from typing import Any, Awaitable, Callable, Literal

import dirtyjson  # type: ignore[import-untyped]
from llmai.shared import AssistantToolCall, Tool  # type: ignore[import-not-found]

from constants.presentation import MAX_NUMBER_OF_SLIDES, MAX_OUTLINE_CONTENT_WORDS
from services.chat.schemas import (
    AddOutlineInput,
    DeleteSlideInput,
    DeleteOutlineInput,
    GenerateAssetsInput,
    GetSmartPresentationContextInput,
    GetSlideAtIndexInput,
    ReadSourceDocumentsInput,
    SaveSmartSlideInput,
    SearchSlidesInput,
    UpdateOutlineInput,
)
from services.chat.presentation_context_store import PresentationContextStore

LOGGER = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ChatToolMode = Literal["presentation", "outline"]
CHART_INSERT_TOOL_FIELDS = {
    "addElement": "element",
    "addComponent": "component",
    "createComponent": "component",
    "updateComponent": "component",
}
TABLE_INSERT_TOOL_FIELDS = CHART_INSERT_TOOL_FIELDS
IMAGE_INSERT_TOOL_FIELDS = CHART_INSERT_TOOL_FIELDS
JSON_OBJECT_STRING_FIELDS = {
    "addNewSlideLayout": ("content",),
    "saveSlide": ("content",),
    "updateSlide": ("content",),
    "addElement": ("element",),
    "updateElement": ("element",),
    "addComponent": ("component",),
    "createComponent": ("component",),
    "updateComponent": ("component",),
}
MAX_TOOL_REPAIR_RETRIES = 1


def _normalize_tool_argument_value(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() == "null":
        return None
    if isinstance(value, list):
        return [_normalize_tool_argument_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _normalize_tool_argument_value(item)
            for key, item in value.items()
        }
    return value


class ChatTools:
    def __init__(
        self,
        memory: PresentationContextStore,
        mode: ChatToolMode = "presentation",
    ):
        self._memory = memory
        self._mode = mode
        self._turn_user_message = ""
        self._generated_assets: list[dict[str, Any]] = []
        self._tool_handlers: dict[str, ToolHandler] = {
            "addOutline": self._add_outline,
            "updateOutline": self._update_outline,
            "deleteOutline": self._delete_outline,
            "getSmartPresentationContext": self._get_smart_presentation_context,
            "readSourceDocuments": self._read_source_documents,
            "searchSlide": self._search_slides,
            "getSlideAtIndex": self._get_slide_at_index,
            "generateAssets": self._generate_assets,
            "saveSlide": self._save_slide,
            "deleteSlide": self._delete_slide,
        }

    def set_turn_context(self, user_message: str) -> None:
        self._turn_user_message = user_message or ""
        self._generated_assets = []

    def get_tool_definitions(self) -> list[Tool]:
        if self._memory.presentation_type == "smart":
            return self._get_smart_tool_definitions()
        return [
            Tool(
                name="addOutline",
                description=(
                    "Insert a new markdown outline item into the outline draft. "
                    "This edits presentation.outlines only and does not require a layout. "
                    f"Do not exceed {MAX_NUMBER_OF_SLIDES} outline slides or "
                    f"{MAX_OUTLINE_CONTENT_WORDS} words in this outline item."
                ),
                schema=AddOutlineInput,
                strict=False,
            ),
            Tool(
                name="updateOutline",
                description=(
                    "Replace the markdown content of one outline item by zero-based index. "
                    "This edits presentation.outlines only and does not require a layout. "
                    f"Keep this outline item within {MAX_OUTLINE_CONTENT_WORDS} words."
                ),
                schema=UpdateOutlineInput,
                strict=False,
            ),
            Tool(
                name="deleteOutline",
                description=(
                    "Delete one outline item by zero-based index. This edits "
                    "presentation.outlines only and does not require a layout."
                ),
                schema=DeleteOutlineInput,
                strict=False,
            ),
            Tool(
                name="readSourceDocuments",
                description=(
                    "Read parsed text from the source document(s) uploaded for this "
                    "presentation, including PDFs. Use when the user refers to an "
                    "uploaded/source PDF, document, file, or the document used to "
                    "generate the deck. Use before summarizing, quoting, extracting "
                    "data, or creating slide content from uploaded documents."
                ),
                schema=ReadSourceDocumentsInput,
                strict=False,
            ),
        ]

    def _get_smart_tool_definitions(self) -> list[Tool]:
        return [
            Tool(
                name="getSmartPresentationContext",
                description=(
                    "Read Smart deck metadata, fonts, outlines, structure, and live "
                    "HTML slide previews. Use before new slides, style changes, or "
                    "multi-slide edits. Prefer includeSlideHtml=false; fetch exact "
                    "target HTML with getSlideAtIndex."
                ),
                schema=GetSmartPresentationContextInput,
                strict=False,
            ),
            Tool(
                name="readSourceDocuments",
                description=(
                    "Read parsed source documents linked to this presentation when "
                    "the user asks to use, summarize, quote, or visualize their content."
                ),
                schema=ReadSourceDocumentsInput,
                strict=False,
            ),
            Tool(
                name="searchSlide",
                description=(
                    "Search rendered Smart slide text and return matching slide indices "
                    "and snippets."
                ),
                schema=SearchSlidesInput,
                strict=False,
            ),
            Tool(
                name="getSlideAtIndex",
                description=(
                    "Read one live Smart HTML slide by zero-based index. Set "
                    "includeFullContent=true before every edit to receive the complete "
                    "authoritative html field."
                ),
                schema=GetSlideAtIndexInput,
                strict=False,
            ),
            Tool(
                name="generateAssets",
                description=(
                    "Generate image or icon assets before inserting new visual URLs "
                    "into Smart slide HTML."
                ),
                schema=GenerateAssetsInput,
                strict=False,
            ),
            Tool(
                name="saveSlide",
                description=(
                    "Replace or insert one Smart HTML slide. Pass the complete HTML "
                    "fragment in html. For an edit, first read the slide, keep its "
                    "design and scripts, and use replaceOldSlideAtIndex=true."
                ),
                schema=SaveSmartSlideInput,
                strict=False,
            ),
            Tool(
                name="deleteSlide",
                description=(
                    "Delete a Smart slide by zero-based index and reindex the rest."
                ),
                schema=DeleteSlideInput,
                strict=False,
            ),
        ]

    async def execute_tool_call(self, tool_call: AssistantToolCall) -> dict[str, Any]:
        handler = self._tool_handlers.get(tool_call.name)
        if not handler:
            return {
                "ok": False,
                "tool": tool_call.name,
                "error": f"Unsupported tool: {tool_call.name}",
                "recovery": {
                    "retryable": False,
                    "message": "Use one of the available chat tools.",
                    "guidance": ["Choose a tool from the tool definitions."],
                },
            }

        parsed_args: dict[str, Any] | None = None
        repair_notes: list[str] = []
        try:
            parsed_args = self._parse_args(tool_call.arguments)
            parsed_args, repair_notes = self._repair_tool_args(
                tool_call.name,
                parsed_args,
            )
            LOGGER.info("Executing chat tool %s", tool_call.name)
            try:
                result = await handler(parsed_args)
            except Exception as first_exc:
                retried = False
                for _attempt in range(MAX_TOOL_REPAIR_RETRIES):
                    retry_args, retry_notes = self._repair_tool_args(
                        tool_call.name,
                        parsed_args,
                        error=str(first_exc),
                    )
                    if not retry_notes or self._args_equivalent(parsed_args, retry_args):
                        break
                    repair_notes.extend(retry_notes)
                    parsed_args = retry_args
                    LOGGER.info(
                        "Retrying chat tool %s after argument repair",
                        tool_call.name,
                    )
                    result = await handler(parsed_args)
                    retried = True
                    break
                if not retried:
                    raise first_exc

            if tool_call.name == "generateAssets":
                self._remember_generated_assets(result)

            response = {"ok": True, "tool": tool_call.name, "result": result}
            if repair_notes:
                response["repair"] = {
                    "applied": True,
                    "notes": repair_notes,
                }
            return response
        except Exception as exc:
            LOGGER.exception("Chat tool failed: %s", tool_call.name)
            return {
                "ok": False,
                "tool": tool_call.name,
                "error": str(exc),
                "repair": {
                    "attempted": bool(repair_notes),
                    "notes": repair_notes,
                },
                "recovery": self._build_tool_recovery(
                    tool_name=tool_call.name,
                    args=parsed_args,
                    error=str(exc),
                ),
            }

    async def _search_slides(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = SearchSlidesInput(**args)
        results = await self._memory.search(payload.query, payload.limit)
        return {
            "query": payload.query,
            "count": len(results),
            "results": results,
        }

    async def _get_slide_at_index(self, args: dict[str, Any]) -> dict[str, Any]:
        normalized_args = dict(args)
        normalized_args.setdefault("includeFullContent", False)
        payload = GetSlideAtIndexInput(**normalized_args)
        slide = await self._memory.get_slide_at_index(
            payload.index,
            include_full_content=payload.include_full_content,
        )
        if not slide and payload.index > 0:
            # Users often refer to slides as 1-based; allow a safe fallback.
            fallback_index = payload.index - 1
            fallback_slide = await self._memory.get_slide_at_index(
                fallback_index,
                include_full_content=payload.include_full_content,
            )
            if fallback_slide:
                return {
                    "found": True,
                    "slide": fallback_slide,
                    "requested_index": payload.index,
                    "resolved_index": fallback_index,
                    "note": (
                        "No slide found at requested index; returned one-based fallback "
                        f"at index {fallback_index}."
                    ),
                }
        if not slide:
            return {
                "found": False,
                "message": f"No slide found at index {payload.index}.",
            }
        return {
            "found": True,
            "slide": slide,
        }

    async def _add_outline(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = AddOutlineInput(**args)
        return await self._memory.add_outline(
            content=payload.content,
            index=payload.index,
        )

    async def _update_outline(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = UpdateOutlineInput(**args)
        return await self._memory.update_outline(
            index=payload.index,
            content=payload.content,
        )

    async def _delete_outline(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = DeleteOutlineInput(**args)
        return await self._memory.delete_outline(index=payload.index)

    async def _get_smart_presentation_context(
        self,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        payload = GetSmartPresentationContextInput(**args)
        return await self._memory.get_smart_presentation_context(
            include_slide_html=payload.include_slide_html,
            max_html_chars_per_slide=payload.max_html_chars_per_slide,
        )

    async def _read_source_documents(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = ReadSourceDocumentsInput(**args)
        return await self._memory.read_source_documents(
            query=payload.query,
            max_chars=payload.max_chars,
        )

    async def _generate_assets(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = GenerateAssetsInput(**args)
        generated_assets: list[dict[str, Any]] = []

        for index, asset in enumerate(payload.assets):
            if asset.kind == "image":
                url = await self._memory.generate_image(asset.prompt)
            else:
                url = await self._memory.generate_icon(asset.prompt)

            generated_assets.append(
                {
                    "index": index,
                    "kind": asset.kind,
                    "prompt": asset.prompt,
                    "url": url,
                }
            )

        return {
            "count": len(generated_assets),
            "assets": generated_assets,
            "message": f"Generated {len(generated_assets)} asset(s).",
        }

    async def _save_slide(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = SaveSmartSlideInput(**args)
        return await self._memory.save_html_slide(
            html=payload.html,
            index=payload.index,
            replace_old_slide_at_index=payload.replace_old_slide_at_index,
            speaker_note=payload.speaker_note,
        )

    async def _delete_slide(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = DeleteSlideInput(**args)
        return await self._memory.delete_slide(index=payload.index)

    @staticmethod
    def _parse_args(arguments: str | None) -> dict[str, Any]:
        if not arguments:
            return {}

        parsed = ChatTools._loads_jsonish(arguments)

        normalized = _normalize_tool_argument_value(
            json.loads(json.dumps(parsed, ensure_ascii=False))
        )
        if isinstance(normalized, dict):
            return normalized

        raise ValueError("Tool arguments must be a JSON object.")

    def _repair_tool_args(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        error: str | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        repaired = dict(args)
        notes: list[str] = []
        self._repair_json_object_string_fields(tool_name, repaired, notes)
        repaired = self._repair_chart_insert_args(
            tool_name,
            repaired,
            notes,
            error=error,
        )
        repaired = self._repair_table_insert_args(
            tool_name,
            repaired,
            notes,
            error=error,
        )
        repaired = self._repair_image_insert_args(
            tool_name,
            repaired,
            notes,
            error=error,
        )
        return repaired, notes

    @staticmethod
    def _repair_json_object_string_fields(
        tool_name: str,
        args: dict[str, Any],
        notes: list[str],
    ) -> None:
        for field_name in JSON_OBJECT_STRING_FIELDS.get(tool_name, ()):
            if field_name not in args:
                continue
            value = args.get(field_name)
            if value is None:
                continue
            if isinstance(value, dict):
                args[field_name] = json.dumps(value, ensure_ascii=False)
                notes.append(
                    f"Converted {field_name} from object to JSON string."
                )
                continue
            if not isinstance(value, str):
                continue
            parsed = ChatTools._loads_jsonish_object(value)
            if parsed is None:
                continue
            canonical = json.dumps(parsed, ensure_ascii=False)
            if canonical != value:
                args[field_name] = canonical
                notes.append(f"Repaired JSON string field {field_name}.")

    def _repair_chart_insert_args(
        self,
        tool_name: str,
        args: dict[str, Any],
        notes: list[str],
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload_field = CHART_INSERT_TOOL_FIELDS.get(tool_name)
        if not payload_field or payload_field not in args:
            return args

        chart_rows = self._extract_chart_rows_from_user_message(
            self._turn_user_message,
        )
        if not chart_rows:
            return args

        payload = self._parse_json_object_field(args.get(payload_field))
        if payload is None:
            return args

        title = self._infer_chart_title_from_user_message(self._turn_user_message)
        if not self._inject_missing_chart_data(payload, chart_rows, title):
            return args

        repaired = dict(args)
        repaired[payload_field] = json.dumps(payload, ensure_ascii=False)
        notes.append(
            "Filled missing chart categories and series.values from the latest user message."
        )
        return repaired

    def _repair_table_insert_args(
        self,
        tool_name: str,
        args: dict[str, Any],
        notes: list[str],
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload_field = TABLE_INSERT_TOOL_FIELDS.get(tool_name)
        if not payload_field or payload_field not in args:
            return args

        table_data = self._extract_table_from_user_message(self._turn_user_message)
        if table_data is None:
            return args

        payload = self._parse_json_object_field(args.get(payload_field))
        if payload is None:
            return args

        if not self._inject_missing_table_data(payload, table_data):
            return args

        repaired = dict(args)
        repaired[payload_field] = json.dumps(payload, ensure_ascii=False)
        notes.append(
            "Filled missing table headers/columns and rows from the latest user message."
        )
        return repaired

    def _repair_image_insert_args(
        self,
        tool_name: str,
        args: dict[str, Any],
        notes: list[str],
        *,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload_field = IMAGE_INSERT_TOOL_FIELDS.get(tool_name)
        if not payload_field or payload_field not in args:
            return args

        payload = self._parse_json_object_field(args.get(payload_field))
        if payload is None:
            return args

        if not self._inject_missing_image_data(payload):
            return args

        repaired = dict(args)
        repaired[payload_field] = json.dumps(payload, ensure_ascii=False)
        notes.append(
            "Filled missing image data from the generated asset URL in this turn."
        )
        return repaired

    @staticmethod
    def _parse_json_object_field(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return json.loads(json.dumps(value, ensure_ascii=False))
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = ChatTools._loads_jsonish_object(value)
        if not isinstance(parsed, dict):
            return None
        return json.loads(json.dumps(parsed, ensure_ascii=False))

    def _remember_generated_assets(self, result: dict[str, Any]) -> None:
        assets = result.get("assets") if isinstance(result, dict) else None
        if not isinstance(assets, list):
            return

        for asset in assets:
            if not isinstance(asset, dict):
                continue
            url = asset.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            self._generated_assets.append(
                {
                    "kind": str(asset.get("kind") or "image"),
                    "prompt": str(asset.get("prompt") or ""),
                    "url": url.strip(),
                }
            )

    @staticmethod
    def _loads_jsonish_object(value: str) -> dict[str, Any] | None:
        try:
            parsed = ChatTools._loads_jsonish(value)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _loads_jsonish(value: str) -> Any:
        last_exc: Exception | None = None
        for candidate in ChatTools._jsonish_candidates(value):
            try:
                return dirtyjson.loads(candidate)
            except Exception as exc:
                last_exc = exc
            try:
                return json.loads(candidate)
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        raise ValueError("JSON value is empty.")

    @staticmethod
    def _jsonish_candidates(value: str) -> list[str]:
        stripped = (value or "").strip()
        if not stripped:
            return []

        candidates = [stripped]
        fence_match = re.search(
            r"```(?:json|javascript|js)?\s*(.*?)```",
            stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if fence_match:
            candidates.append(fence_match.group(1).strip())

        for opener, closer in (("{", "}"), ("[", "]")):
            start = stripped.find(opener)
            end = stripped.rfind(closer)
            if start != -1 and end > start:
                candidates.append(stripped[start : end + 1].strip())

        unique: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            unique.append(candidate)
        return unique

    @classmethod
    def _inject_missing_chart_data(
        cls,
        node: Any,
        rows: list[dict[str, Any]],
        title: str,
    ) -> bool:
        from services.chat.slide_ui_helpers import _chart_element_has_explicit_data

        changed = False
        if isinstance(node, dict):
            if node.get("type") == "chart" and not _chart_element_has_explicit_data(node):
                categories = [row["label"] for row in rows]
                values = [row["value"] for row in rows]
                node.setdefault("chart_type", "bar")
                node.setdefault("title", title)
                node["categories"] = categories
                node["series"] = [{"name": title or "Series 1", "values": values}]
                node["data"] = [
                    {"label": row["label"], "value": row["value"]}
                    for row in rows
                ]
                changed = True
            for value in node.values():
                changed = cls._inject_missing_chart_data(value, rows, title) or changed
        elif isinstance(node, list):
            for value in node:
                changed = cls._inject_missing_chart_data(value, rows, title) or changed
        return changed

    @classmethod
    def _inject_missing_table_data(
        cls,
        node: Any,
        table_data: dict[str, Any],
    ) -> bool:
        from services.chat.slide_ui_helpers import _table_element_has_explicit_data

        changed = False
        if isinstance(node, dict):
            if node.get("type") == "table" and not _table_element_has_explicit_data(node):
                columns = list(table_data["columns"])
                rows = [list(row) for row in table_data["rows"]]
                node["columns"] = columns
                node["rows"] = rows
                node.setdefault("min_columns", 1)
                node.setdefault("max_columns", max(len(columns), 1))
                node.setdefault("min_rows", 1)
                node.setdefault("max_rows", max(len(rows), 1))
                changed = True
            for value in node.values():
                changed = cls._inject_missing_table_data(value, table_data) or changed
        elif isinstance(node, list):
            for value in node:
                changed = cls._inject_missing_table_data(value, table_data) or changed
        return changed

    def _inject_missing_image_data(self, node: Any) -> bool:
        from services.chat.slide_ui_helpers import _image_element_has_explicit_data

        changed = False
        if isinstance(node, dict):
            if node.get("type") == "image" and not _image_element_has_explicit_data(node):
                asset = self._latest_generated_asset_for_image(
                    is_icon=node.get("is_icon") is True,
                )
                if asset is not None:
                    node["data"] = asset["url"]
                    node.setdefault("is_icon", asset.get("kind") == "icon")
                    prompt = asset.get("prompt")
                    if isinstance(prompt, str) and prompt.strip():
                        node.setdefault("prompt", prompt.strip())
                    changed = True
            for value in node.values():
                changed = self._inject_missing_image_data(value) or changed
        elif isinstance(node, list):
            for value in node:
                changed = self._inject_missing_image_data(value) or changed
        return changed

    def _latest_generated_asset_for_image(
        self,
        *,
        is_icon: bool,
    ) -> dict[str, Any] | None:
        preferred_kind = "icon" if is_icon else "image"
        for asset in reversed(self._generated_assets):
            if asset.get("kind") == preferred_kind and asset.get("url"):
                return asset
        for asset in reversed(self._generated_assets):
            if asset.get("url"):
                return asset
        return None

    @classmethod
    def _extract_chart_rows_from_user_message(
        cls,
        user_message: str,
    ) -> list[dict[str, Any]]:
        text = cls._strip_ui_context_prefix(user_message)
        if not text:
            return []

        rows: list[dict[str, Any]] = []
        seen_labels: set[str] = set()
        segments = re.split(r"[\n;,|]+|\s+\band\b\s+", text, flags=re.IGNORECASE)
        for segment in segments:
            segment = segment.strip(" \t\r\n.:-–—")
            if not segment:
                continue
            for match in re.finditer(
                r"(?P<label>[A-Za-z][A-Za-z0-9&'./() -]{0,80}?)"
                r"\s*(?:[:=\-–—]|\bhas\b|\bhave\b|\bwith\b)?\s+"
                r"(?P<value>[-+]?(?:\d[\d,]*(?:\.\d+)?|\.\d+))\b",
                segment,
                flags=re.IGNORECASE,
            ):
                label = cls._clean_chart_label(match.group("label"))
                if not label:
                    continue
                number = cls._parse_chart_number(match.group("value"))
                if number is None:
                    continue
                normalized_label = label.lower()
                if normalized_label in seen_labels:
                    continue
                seen_labels.add(normalized_label)
                rows.append({"label": label, "value": number})
                if len(rows) >= 12:
                    return rows
        return rows if len(rows) >= 2 else []

    @classmethod
    def _extract_table_from_user_message(
        cls,
        user_message: str,
    ) -> dict[str, Any] | None:
        text = cls._strip_ui_context_prefix(user_message)
        if not text:
            return None

        marker_match = re.search(r"\bdata\s*:\s*(?P<data>.+)$", text, re.IGNORECASE | re.DOTALL)
        if marker_match:
            header_text = text[: marker_match.start()]
            headers = cls._extract_table_headers(header_text)
            rows = cls._parse_table_rows(marker_match.group("data"))
            if headers and rows:
                normalized_rows = cls._align_table_rows(rows, len(headers))
                if normalized_rows:
                    return {"columns": headers, "rows": normalized_rows}

        csv_rows = cls._parse_table_rows(text, row_split_pattern=r"[\n;]+")
        if len(csv_rows) >= 2:
            headers = csv_rows[0]
            rows = cls._align_table_rows(csv_rows[1:], len(headers))
            if headers and rows:
                return {"columns": headers, "rows": rows}

        return None

    @classmethod
    def _extract_table_headers(cls, text: str) -> list[str]:
        patterns = (
            r"\bfirst\s+row\s+with\s+(?P<headers>[^.\n;]+)",
            r"\bheaders?\s*(?:are|with|:)?\s+(?P<headers>[^.\n;]+)",
            r"\bcolumns?\s*(?:are|with|:)?\s+(?P<headers>[^.\n;]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            headers = cls._split_table_cells(match.group("headers"))
            if len(headers) >= 1:
                return headers
        return []

    @classmethod
    def _parse_table_rows(
        cls,
        text: str,
        *,
        row_split_pattern: str = r"[;\n]+",
    ) -> list[list[str]]:
        rows: list[list[str]] = []
        for raw_row in re.split(row_split_pattern, text):
            cells = cls._split_table_cells(raw_row)
            if cells:
                rows.append(cells)
        return rows

    @staticmethod
    def _split_table_cells(text: str) -> list[str]:
        cells = [
            cell.strip(" \t\r\n.:-–—")
            for cell in re.split(r"\s*\|\s*|\s*,\s*", text or "")
        ]
        return [cell for cell in cells if cell]

    @staticmethod
    def _align_table_rows(rows: list[list[str]], column_count: int) -> list[list[str]]:
        aligned: list[list[str]] = []
        for row in rows:
            if len(row) == column_count:
                aligned.append(row)
        return aligned

    @staticmethod
    def _clean_chart_label(value: str) -> str:
        label = re.sub(r"\s+", " ", value or "").strip(" \t\r\n.:-–—")
        label = re.sub(
            r"^(?:and|the|for|category|label|value|metric|series)\s+",
            "",
            label,
            flags=re.IGNORECASE,
        ).strip(" \t\r\n.:-–—")
        if not label:
            return ""
        if label.lower() in {
            "slide",
            "index",
            "chart",
            "bar chart",
            "line chart",
            "user message",
        }:
            return ""
        if label == label.lower():
            return label[:1].upper() + label[1:]
        return label

    @staticmethod
    def _parse_chart_number(value: str) -> float | int | None:
        try:
            number = float(str(value).replace(",", ""))
        except ValueError:
            return None
        if not number == number or number in {float("inf"), float("-inf")}:
            return None
        return int(number) if number.is_integer() else number

    @classmethod
    def _infer_chart_title_from_user_message(cls, user_message: str) -> str:
        text = cls._strip_ui_context_prefix(user_message)
        quoted_title = re.search(
            r"\b(?:titled|called|named)\s+[\"']([^\"']{1,80})[\"']",
            text,
            flags=re.IGNORECASE,
        )
        if quoted_title:
            return quoted_title.group(1).strip()

        count_title = re.search(
            r"\b(?:number\s+of|no\.?\s*of|no\s+of)\s+"
            r"(?P<title>[A-Za-z][A-Za-z ]{1,40}?)"
            r"(?:\s+(?:the|for|by|of|that|which)\b|[.,;\n]|$)",
            text,
            flags=re.IGNORECASE,
        )
        if count_title:
            title = count_title.group("title").strip()
            if title:
                return title[:1].upper() + title[1:]

        lowered = text.lower()
        for keyword, title in (
            ("goal", "Goals"),
            ("revenue", "Revenue"),
            ("sales", "Sales"),
            ("profit", "Profit"),
            ("age", "Age"),
        ):
            if keyword in lowered:
                return title
        return "Chart"

    @staticmethod
    def _strip_ui_context_prefix(user_message: str) -> str:
        marker = "\nUser message:"
        if not user_message.startswith("UI context:"):
            return user_message.strip()
        marker_index = user_message.find(marker)
        if marker_index == -1:
            return user_message.strip()
        return user_message[marker_index + len(marker) :].lstrip()

    @staticmethod
    def _args_equivalent(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return json.dumps(
            left,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ) == json.dumps(
            right,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

    @classmethod
    def _build_tool_recovery(
        cls,
        *,
        tool_name: str,
        args: dict[str, Any] | None,
        error: str,
    ) -> dict[str, Any]:
        normalized_error = (error or "").lower()
        guidance: list[str] = []
        expected: dict[str, Any] = {}
        retryable = True

        if (
            tool_name not in CHART_INSERT_TOOL_FIELDS
            and tool_name not in JSON_OBJECT_STRING_FIELDS
        ):
            guidance.append("Review the tool schema and retry with corrected arguments.")

        if "reusable block available" in normalized_error:
            guidance.append(
                "Use getAvailableBlocks with includeFullContent=true for the "
                "returned block_id, adapt that component JSON, then retry with "
                "addComponent/createComponent and sourceBlockId."
            )
            expected["block_workflow"] = {
                "discovery": {
                    "tool": "getAvailableBlocks",
                    "arguments": {
                        "blockId": "returned block_id",
                        "includeFullContent": True,
                    },
                },
                "insert": {
                    "tool": "addComponent",
                    "arguments": {
                        "component": "JSON string adapted from returned block.component",
                        "sourceBlockId": "returned block_id",
                    },
                },
            }

        json_fields = JSON_OBJECT_STRING_FIELDS.get(tool_name, ())
        if json_fields:
            fields = ", ".join(json_fields)
            guidance.append(
                f"Ensure {fields} is a JSON-serialized object string, not prose."
            )
            expected["json_object_string_fields"] = list(json_fields)

        if "chart elements must include numeric data" in normalized_error:
            guidance.append(
                "For chart elements include categories and series with numeric values before retrying."
            )
            expected["chart"] = {
                "type": "chart",
                "chart_type": "bar",
                "categories": ["Label A", "Label B"],
                "series": [{"name": "Series name", "values": [1, 2]}],
            }

        if "table elements must include" in normalized_error:
            guidance.append(
                "For table elements include columns or headers plus rows before retrying."
            )
            expected["table"] = {
                "type": "table",
                "columns": ["Name", "Age", "Department"],
                "rows": [["Ghanshyam", "30", "QA"], ["Sudeep", "33", "AI"]],
            }

        if "image elements must include" in normalized_error:
            guidance.append(
                "For image elements call generateAssets first, then include the returned URL as data before retrying."
            )
            expected["image"] = {
                "type": "image",
                "data": "/app_data/images/generated.png",
                "is_icon": False,
            }

        if "validation error" in normalized_error:
            guidance.append(
                "Use the field names and aliases from the tool schema, include required nullable fields as null, and remove unsupported keys."
            )

        if "json" in normalized_error or "expecting value" in normalized_error:
            guidance.append(
                "Return valid JSON only for tool arguments; avoid Markdown fences in tool-call arguments."
            )

        if "no slide found" in normalized_error or "was not found" in normalized_error:
            guidance.append(
                "Inspect the deck with getSlideAtIndex or searchSlide and retry with the returned slide index, componentId, or elementPath."
            )

        if "unsupported tool" in normalized_error:
            retryable = False
            guidance = ["Choose one of the available tool names from the current tool definitions."]

        if not guidance:
            guidance.append("Fix the arguments based on the error and retry once.")

        recovery: dict[str, Any] = {
            "retryable": retryable,
            "message": "Repair the tool arguments before retrying." if retryable else "Do not retry this exact tool call.",
            "guidance": guidance,
        }
        if expected:
            recovery["expected"] = expected
        if args is not None:
            recovery["received_keys"] = sorted(str(key) for key in args.keys())
        return recovery

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit]}..."
