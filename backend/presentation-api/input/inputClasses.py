from pydantic import BaseModel,model_validator
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


class PipelineData(BaseModel):
    diagram_type: Literal["pipeline"]
    steps: List[str]


class GridItem(BaseModel):
    use_case: str
    technologies: List[str]


class GridData(BaseModel):
    diagram_type: Literal["grid"]
    items: List[GridItem]

class TableData(BaseModel):
    columns: List[str]
    rows: List[List[str]]

class SlideObject(BaseModel):
    object_id: str

    # type: Literal[
    #     "text",
    #     "table",
    #     "chart",
    #     "diagram",
    #     "image",
    #     "icon",
    #     "callout",
    #     "citation"
    # ]

    type: Literal[
        "text",
        "table",
        "diagram",
        "callout"
    ]

    role: Optional[str] = None

    text: Optional[str] = None

    data: Optional[Any] = None

    source_chunk_ids: List[str] = []

    locked: bool = False

    @model_validator(mode="after")
    def validate_object_data(self):
        if self.type == "diagram":
            if self.data is None:
                raise ValueError("Diagram objects require data")

            diagram_type = self.data.get("diagram_type")

            if diagram_type == "pipeline":
                PipelineData.model_validate(self.data)

            elif diagram_type == "grid":
                GridData.model_validate(self.data)

            else:
                raise ValueError(
                    f"Unsupported diagram_type: {diagram_type}"
                )

        elif self.type == "table":
            if self.data is None:
                raise ValueError("Table objects require data")

            TableData.model_validate(self.data)

        return self

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


class SlideSpecCollection(BaseModel):
    slides: List[SlideSpec]

class TableData(BaseModel):
    columns: List[str]
    rows: List[List[str]]