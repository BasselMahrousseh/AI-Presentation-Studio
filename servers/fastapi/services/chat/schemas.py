from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constants.presentation import MAX_OUTLINE_CONTENT_WORDS


class StrictSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpenAIStrictSchemaModel(StrictSchemaModel):
    @model_validator(mode="before")
    @classmethod
    def populate_missing_fields_with_none(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        for field_name, field in cls.model_fields.items():
            alias = field.alias
            if field_name in normalized or (alias and alias in normalized):
                continue
            normalized[alias or field_name] = None
        return normalized


class AddOutlineInput(OpenAIStrictSchemaModel):
    content: str = Field(
        ...,
        min_length=1,
        max_length=20000,
        description=f"Markdown content for the new outline slide. Maximum {MAX_OUTLINE_CONTENT_WORDS} words.",
    )
    index: int | None = Field(
        ...,
        ge=0,
        le=1000,
        description="Zero-based insert index. Use null to append to the end.",
    )


class GetOutlineInput(OpenAIStrictSchemaModel):
    """No arguments: always returns every outline slide."""


class UpdateOutlineInput(StrictSchemaModel):
    index: int = Field(ge=0, le=1000)
    content: str = Field(
        min_length=1,
        max_length=20000,
        description=f"Replacement markdown content for this outline slide. Maximum {MAX_OUTLINE_CONTENT_WORDS} words.",
    )


class DeleteOutlineInput(StrictSchemaModel):
    index: int = Field(ge=0, le=1000)


class GetSlideAtIndexInput(StrictSchemaModel):
    index: int = Field(ge=0, le=1000)
    include_full_content: bool = Field(alias="includeFullContent")

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class GetSmartPresentationContextInput(StrictSchemaModel):
    include_slide_html: bool = Field(default=False, alias="includeSlideHtml")
    max_html_chars_per_slide: int = Field(
        default=0,
        alias="maxHtmlCharsPerSlide",
        ge=0,
        le=50000,
        description=(
            "Optional HTML prefix length per slide. Use 0 for complete HTML when "
            "includeSlideHtml is true."
        ),
    )

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class SearchSlidesInput(StrictSchemaModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(ge=1, le=10)


class ReadSourceDocumentsInput(OpenAIStrictSchemaModel):
    query: str | None = Field(
        ...,
        min_length=1,
        max_length=1000,
        description=(
            "Optional focus query for retrieving uploaded/source document content. "
            "Use null when the user asks for a general summary."
        ),
    )
    max_chars: int | None = Field(
        ...,
        alias="maxChars",
        ge=1000,
        le=30000,
        description="Maximum document text characters to return. Use null for the default.",
    )

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class SearchWebInput(OpenAIStrictSchemaModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Search-engine-style query of at most 12 words. Keep names, versions, and "
            "the year when relevant."
        ),
    )


class GenerateAssetItemInput(StrictSchemaModel):
    kind: Literal["image", "icon"]
    prompt: str = Field(
        min_length=1,
        max_length=4000,
        description="Image prompt or icon search query.",
    )


class GenerateAssetsInput(StrictSchemaModel):
    assets: list[GenerateAssetItemInput] = Field(min_length=1, max_length=12)


class SaveSmartSlideInput(StrictSchemaModel):
    html: str = Field(
        min_length=1,
        max_length=500000,
        description="Complete replacement HTML fragment for one Smart slide.",
    )
    index: int = Field(ge=0, le=1000)
    replace_old_slide_at_index: bool = Field(alias="replaceOldSlideAtIndex")
    speaker_note: str | None = Field(
        default=None,
        alias="speakerNote",
        max_length=10000,
    )
    edit_prompt: str | None = Field(
        default=None,
        alias="editPrompt",
        max_length=4000,
    )

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class DeleteSlideInput(StrictSchemaModel):
    index: int = Field(ge=0, le=1000)


DataLabelPosition = Literal["base", "mid", "top", "outside"]


class SlideElementTableValueInput(StrictSchemaModel):
    text: str = Field(min_length=0, max_length=5000)


SlideElementTableValue = (
    str | int | float | bool | None | SlideElementTableValueInput
)


