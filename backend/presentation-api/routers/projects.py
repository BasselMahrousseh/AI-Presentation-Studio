from fastapi import APIRouter, UploadFile, File
from input.inputClasses import ProjectCreate
import uuid
from datetime import datetime, timezone

router = APIRouter(prefix="/projects", tags=["Projects"])

projects_db = []  
sources_db = []

@router.post("")
async def create_project(project: ProjectCreate):
    project_id = len(projects_db) + 1
    projects_db.append(project)
    return {
        "project_id": project_id,
        "status": "CREATED",
        "received": {
            "owner_id": project.owner_id,
            "team_id": project.team_id,
            "title": project.title,
            "classification": project.classification,
        },
    }


@router.get("/{project_id}")
async def get_project(project_id: str,):

    #We find the projects
    for i in range(len(projects_db)):
        if i+1 == int(project_id):
            return {
                "project_id": project_id,
                "status": "FOUND",
                "project_details": {
                    "owner_id": projects_db[i].owner_id,
                    "team_id": projects_db[i].team_id,
                    "title": projects_db[i].title,
                    "classification": projects_db[i].classification,
                },
            }
    return {"project_id": project_id, "status": "NOT_FOUND", "message": "Project not found."}


@router.post("/{project_id}/sources")
async def upload_source(project_id: str, file: UploadFile = File(...)):
    # 1. Verify project exists
    # (Using UUID string checks rather than list indices)

    source_id = str(uuid.uuid4())
    current_time = datetime.now(timezone.utc).isoformat()

    # 2. Read file binary stream
    content = await file.read()
    file_size = len(content)

    # 3. Save binary to Object Storage (Mocked call for now)
    # object_storage_client.upload(
    #     key=f"aips/dev/projects/{project_id}/sources/{source_id}/raw",
    #     data=content
    # )

    # 4. Save metadata record to DB
    source_record = {
        "source_id": source_id,
        "project_id": project_id,
        "filename": file.filename,
        "content_type": file.content_type or "application/octet-stream",
        "file_size_bytes": file_size,
        "status": "PROCESSING",  # Set to PROCESSING so ingestion worker can pick it up
        "created_at": current_time,
    }

    sources_db.append(source_record)

    return source_record


@router.post("/{project_id}/decks")
async def create_deck(project_id: str):
    
    return {"project_id": project_id, "status": "DUMMY", "message": "Deck creation placeholder."}