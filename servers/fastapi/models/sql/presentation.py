from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional
import uuid
import copy
from sqlalchemy import JSON, Column, DateTime, Enum as SAEnum, ForeignKey, String
from sqlmodel import Boolean, Field, SQLModel

from models.presentation_outline_model import PresentationOutlineModel
from models.presentation_structure_model import PresentationStructureModel
from models.presentation_layout import PresentationLayoutModel
from utils.datetime_utils import get_current_utc_datetime
from api.v1.auth.context import get_current_owner_id


class PresentationVersion(str, Enum):
    V1_STANDARD = "v1-standard"
    V2_STANDARD = "v2-standard"


class PresentationModel(SQLModel, table=True):
    __tablename__ = "presentations"

    id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    owner_id: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        exclude=True,
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    version: PresentationVersion = Field(
        sa_column=Column(
            SAEnum(
                PresentationVersion,
                values_callable=lambda enum: [item.value for item in enum],
                name="presentation_version",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
    )
    content: str
    n_slides: int
    language: str
    title: Optional[str] = None
    file_paths: Optional[List[str]] = Field(sa_column=Column(JSON), default=None)
    outlines: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, default=get_current_utc_datetime
        ),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=get_current_utc_datetime,
            onupdate=get_current_utc_datetime,
        ),
    )
    layout: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    structure: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    instructions: Optional[str] = Field(sa_column=Column(String), default=None)
    tone: Optional[str] = Field(sa_column=Column(String), default=None)
    verbosity: Optional[str] = Field(sa_column=Column(String), default=None)
    include_table_of_contents: bool = Field(sa_column=Column(Boolean), default=False)
    include_title_slide: bool = Field(sa_column=Column(Boolean), default=True)
    web_search: bool = Field(sa_column=Column(Boolean), default=False)
    theme: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    fonts: Optional[dict] = Field(sa_column=Column(JSON), default=None)
    generation_mode: Literal["standard", "smart"] = Field(
        sa_column=Column(String, nullable=False, default="standard"),
        default="standard",
    )
    community_design_ids: Optional[List[int]] = Field(
        sa_column=Column(JSON), default=None
    )
    smart_template: Optional[str] = Field(
        sa_column=Column(String, nullable=True), default=None
    )
    smart_brand_colors: Optional[List[str]] = Field(
        sa_column=Column(JSON), default=None
    )
    # "in_progress" while a Smart-mode generation is still streaming, "completed"
    # once it finishes. None for rows created before this column existed, and for
    # every non-Smart presentation, which persist slides in one shot as before.
    generation_status: Optional[Literal["in_progress", "completed"]] = Field(
        sa_column=Column(String, nullable=True), default=None
    )
    # None until stream_outlines()'s explicit-slide-structure detection has run
    # at least once for this presentation; True/False afterwards, and never
    # recomputed once set. Exists specifically so a repeat call to
    # GET /outlines/stream/{id} (a frontend reconnect retry, a manual page
    # reload, etc.) reuses the first call's detection decision instead of
    # re-deriving it from n_slides - which this same endpoint backfills from 0
    # to a real slide count as a side effect of a prior successful call, and
    # would otherwise silently flip this decision on every subsequent call.
    # See stream_outlines() in api/v1/ppt/endpoints/outlines.py.
    has_explicit_slide_structure: Optional[bool] = Field(
        sa_column=Column(Boolean, nullable=True), default=None
    )
    # Flat list of VisualQualityFlag dicts (models/extraction_quality.py), recomputed
    # fresh on every stream_outlines() call from the presentation's own file_paths -
    # unlike has_explicit_slide_structure, there is no poisoned-fallback risk here, so
    # simply overwriting on each call is safe and keeps this in sync with the files.
    source_quality_flags: Optional[list] = Field(sa_column=Column(JSON), default=None)
    # Group keys (see extraction_quality.group_quality_flags) the user has explicitly
    # accepted as "keep as static images" in the outline-review Data Quality panel.
    # Mutated only by the dedicated acknowledge endpoint - stream_outlines() must never
    # touch this, or a reconnect/retry would silently re-block an already-cleared group.
    acknowledged_quality_flag_groups: Optional[List[str]] = Field(
        sa_column=Column(JSON), default=None
    )

    def get_new_presentation(self):
        return PresentationModel(
            id=uuid.uuid4(),
            owner_id=self.owner_id,
            version=self.version,
            content=self.content,
            n_slides=self.n_slides,
            language=self.language,
            title=self.title,
            file_paths=copy.deepcopy(self.file_paths),
            outlines=copy.deepcopy(self.outlines),
            layout=copy.deepcopy(self.layout),
            structure=copy.deepcopy(self.structure),
            instructions=self.instructions,
            tone=self.tone,
            verbosity=self.verbosity,
            include_table_of_contents=self.include_table_of_contents,
            include_title_slide=self.include_title_slide,
            web_search=self.web_search,
            theme=copy.deepcopy(self.theme),
            fonts=copy.deepcopy(self.fonts),
            generation_mode=self.generation_mode,
            community_design_ids=copy.deepcopy(self.community_design_ids),
            smart_template=self.smart_template,
            smart_brand_colors=copy.deepcopy(self.smart_brand_colors),
        )

    def get_presentation_outline(self):
        if not self.outlines:
            return None
        return PresentationOutlineModel(**self.outlines)

    def get_layout(self):
        return PresentationLayoutModel(**self.layout)

    def set_layout(self, layout: PresentationLayoutModel):
        self.layout = layout.model_dump()

    def get_structure(self):
        if not self.structure:
            return None
        return PresentationStructureModel(**self.structure)

    def set_structure(self, structure: PresentationStructureModel):
        self.structure = structure.model_dump()
