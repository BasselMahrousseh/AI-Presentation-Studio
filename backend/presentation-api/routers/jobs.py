from fastapi import APIRouter

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"]
)

@router.get("/{job_id}")
async def get_job(job_id: str):
    pass


@router.get("/{job_id}/events")
async def stream_job_events(job_id: str):
    pass


@router.post("/{job_id}:cancel")
async def cancel_job(job_id: str):
    pass