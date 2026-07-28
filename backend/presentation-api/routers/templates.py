from fastapi import APIRouter

router = APIRouter(
    prefix="/templates",
    tags=["Templates"]
)

@router.get("")
async def list_templates():
    pass


@router.post("")
async def create_template():
    pass


@router.post("/{template_id}/versions/{version_id}:publish")
async def publish_template(
    template_id: str,
    version_id: str
):
    pass