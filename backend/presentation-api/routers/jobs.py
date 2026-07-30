from fastapi import APIRouter
from services.deckService import getJobFromQueue

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"]
)

@router.get("/{job_id}")
async def get_job(job_id: str):
    job = getJobFromQueue(job_id)

    if job is None:
        return {"error": "Job not found"}

    return {
        "job_id": job.JOB_ID,
        "status": job.STATUS,
        "current_stage": job.CURRENT_STAGE,
        "progress": job.PROGRESS,
    }


@router.get("/{job_id}/events")
async def stream_job_events(job_id: str):
    pass


@router.post("/{job_id}:cancel")
async def cancel_job(job_id: str):
    pass