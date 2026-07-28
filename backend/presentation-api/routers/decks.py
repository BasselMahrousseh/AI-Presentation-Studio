from fastapi import APIRouter

router = APIRouter(
    prefix="/decks",
    tags=["Decks"]
)

@router.post("/{deck_id}/generations")
async def start_generation(deck_id: str):
    pass


@router.get("/{deck_id}/versions/{version_id}")
async def get_deck_version(
    deck_id: str,
    version_id: str
):
    pass


@router.post("/{deck_id}/versions/{version_id}/slides/{slide_no}:regenerate")
async def regenerate_slide(
    deck_id: str,
    version_id: str,
    slide_no: int
):
    pass


@router.post("/{deck_id}/versions/{version_id}/slides/{slide_no}:edit")
async def edit_slide(
    deck_id: str,
    version_id: str,
    slide_no: int
):
    pass


@router.post("/{deck_id}/versions/{version_id}:export")
async def export_deck(
    deck_id: str,
    version_id: str
):
    pass