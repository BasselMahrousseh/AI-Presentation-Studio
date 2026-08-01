# #FIX PROJECT ID 
# MIGHT NEED TO IMPLEMENT RABBITMQ/REDIS + CELERY
#SETUP DATABASES


from fastapi import APIRouter,Response
from input.inputClasses import DeckGeneration
from database.models import Job 
import uuid
from services.deckService import addJobToQueue

router = APIRouter(
    prefix="/decks",
    tags=["Decks"]
)

@router.post("/{deck_id}/generations")
async def start_generation(generation: DeckGeneration):
    deck_id = generation.deck_id
    language = generation.language
    prompt = generation.prompt

    # #Calls an end point with prompt as input -> returns deck brief
    # #Uses deck brief to call again to generate deck plan
    # #uses deck plan to call again to generate slide spec


    job = Job(
        JOB_ID=2,
        PROJECT_ID=1,
        TYPE="FULL_DECK_GENERATION",
        STATUS="CREATED",
        CURRENT_STAGE="INITIAL",
        PROGRESS=0
    )
    
    ppt = addJobToQueue(job,generation.prompt)

    # return {
    #     "job_id": job.JOB_ID,
    #     "status": job.STATUS,
    #     "message": "Generation started"
    # }

    return Response(
        content=ppt,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )

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