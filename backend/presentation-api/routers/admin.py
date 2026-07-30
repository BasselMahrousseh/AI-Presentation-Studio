from fastapi import APIRouter

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)

@router.get("/usage")
async def get_usage():
    pass