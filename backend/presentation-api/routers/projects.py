from fastapi import APIRouter

router = APIRouter(prefix="/projects", tags=["Projects"])

@router.post("")
async def create_project():
    ...

@router.get("/{project_id}")
async def get_project(project_id: str):
    ...

@router.post("/{project_id}/sources")
async def upload_source(project_id: str):
    ...

@router.post("/{project_id}/decks")
async def create_deck(project_id: str):
    ...