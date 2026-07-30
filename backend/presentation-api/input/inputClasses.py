from pydantic import BaseModel
from typing import Any, List, Literal, Optional


class ProjectCreate(BaseModel):
    owner_id: str
    team_id: str
    title: str
    classification: str


class DeckGeneration(BaseModel):
    deck_id: str
    language: str
    prompt: str


class DeckBrief(BaseModel):
    title: str
    audience: str
    objective: str
    decision_sought: Optional[str] = None

    language: Literal["en", "ar", "bilingual"]

    slide_count: int

    tone: Literal[
        "technical",
        "operational",
        "concise"
    ]

    classification: Literal[
        "PUBLIC",
        "INTERNAL",
        "CONFIDENTIAL",
        "RESTRICTED"
    ]

    source_ids: List[str] = []

    requirements: List[str] = []


class DeckPlanSlide(BaseModel):
    slide_id: str
    sequence: int
    purpose: str
    message: str
    archetype: str

    evidence_chunk_ids: List[str] = []

    visual_intent: Optional[str] = None

    requires_review: bool = False


class DeckPlan(BaseModel):
    deck_title: str
    narrative: str

    slides: List[DeckPlanSlide]




class SlideObject(BaseModel):
    object_id: str

    type: Literal[
        "text",
        "table",
        "chart",
        "diagram",
        "image",
        "icon",
        "callout",
        "citation"
    ]

    role: Optional[str] = None

    text: Optional[str] = None

    data: Optional[Any] = None

    source_chunk_ids: List[str] = []

    locked: bool = False


class SlideSpec(BaseModel):
    slide_id: str

    archetype: str

    title: str

    message: str

    direction: Literal[
        "ltr",
        "rtl",
        "mixed"
    ]

    objects: List[SlideObject]

    speaker_notes: Optional[str] = None

    requires_review: bool = False