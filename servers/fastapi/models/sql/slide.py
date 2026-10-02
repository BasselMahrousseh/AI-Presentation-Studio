import copy
from typing import Optional
import uuid

from sqlalchemy import ForeignKey
from sqlmodel import Field, Column, SQLModel

from api.v1.auth.context import get_current_owner_id
from utils.sql_types import PortableUUID, PortableJSON, auto_text, label


class SlideModel(SQLModel, table=True):
    __tablename__ = "GENAI_WORKSPACE_SLIDE"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, sa_column=Column(PortableUUID, primary_key=True, default=uuid.uuid4))
    owner_id: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        exclude=True,
        sa_column=Column(
            ForeignKey("GENAI_WORKSPACE_STUDIO_USER.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    presentation: uuid.UUID = Field(
        sa_column=Column(ForeignKey("GENAI_WORKSPACE_PRESENTATION.id", ondelete="CASCADE"), index=True)
    )
    layout_group: str = Field(sa_column=Column(label(255, auto=True), nullable=False))
    layout: str = Field(sa_column=Column(label(255, auto=True), nullable=False))
    index: int
    content: dict = Field(sa_column=Column(PortableJSON))
    html_content: Optional[str] = Field(default=None, sa_column=Column(auto_text()))
    speaker_note: Optional[str] = Field(default=None, sa_column=Column(auto_text()))
    properties: Optional[dict] = Field(sa_column=Column(PortableJSON))
    ui: Optional[dict] = Field(default=None, sa_column=Column(PortableJSON, nullable=True))

    def get_new_slide(self, presentation: uuid.UUID, content: Optional[dict] = None):
        return SlideModel(
            id=uuid.uuid4(),
            owner_id=self.owner_id,
            presentation=presentation,
            layout_group=self.layout_group,
            layout=self.layout,
            index=self.index,
            speaker_note=self.speaker_note,
            content=copy.deepcopy(content or self.content),
            html_content=self.html_content,
            properties=copy.deepcopy(self.properties),
            ui=copy.deepcopy(self.ui),
        )
