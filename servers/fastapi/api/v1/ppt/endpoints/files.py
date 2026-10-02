import os
import asyncio
from typing import Annotated, List, Optional
from fastapi import APIRouter, Body, HTTPException, UploadFile

from constants.documents import UPLOAD_ACCEPTED_FILE_TYPES
from models.decomposed_file_info import DecomposedFileInfo
from services.temp_file_service import TEMP_FILE_SERVICE
from services.documents_loader import DocumentsLoader
from services.asset_storage import get_asset_storage
import uuid
from utils.validators import validate_files

FILES_ROUTER = APIRouter(prefix="/files", tags=["Files"])


@FILES_ROUTER.post("/upload", response_model=List[str])
async def upload_files(files: Optional[List[UploadFile]]):
    if not files:
        raise HTTPException(400, "Documents are required")

    temp_dir = TEMP_FILE_SERVICE.create_temp_dir(str(uuid.uuid4()))

    validate_files(files, True, True, 100, UPLOAD_ACCEPTED_FILE_TYPES)

    temp_files: List[str] = []
    if files:
        for each_file in files:
            temp_path = TEMP_FILE_SERVICE.create_temp_file_path(
                each_file.filename, temp_dir
            )
            with open(temp_path, "wb") as f:
                content = await each_file.read()
                f.write(content)

            temp_files.append(await asyncio.to_thread(
                get_asset_storage().publish_new, temp_path, "uploads"
            ))

    return temp_files


@FILES_ROUTER.post("/decompose", response_model=List[DecomposedFileInfo])
async def decompose_files(
    file_paths: Annotated[List[str], Body(embed=True)],
    language: Annotated[Optional[str], Body()] = None,
):
    temp_dir = TEMP_FILE_SERVICE.create_temp_dir(str(uuid.uuid4()))
    references = await asyncio.to_thread(TEMP_FILE_SERVICE.validate_file_references, file_paths)
    resolved_file_paths = await asyncio.to_thread(TEMP_FILE_SERVICE.resolve_existing_temp_paths, references)

    txt_files = []
    other_files = []
    for file_path in resolved_file_paths:
        if file_path.endswith(".txt"):
            txt_files.append(file_path)
        else:
            other_files.append(file_path)

    documents_loader = await asyncio.to_thread(
        DocumentsLoader, file_paths=other_files, presentation_language=language
    )
    await documents_loader.load_documents(temp_dir)
    parsed_documents = documents_loader.documents

    response = []
    for index, parsed_doc in enumerate(parsed_documents):
        file_path = TEMP_FILE_SERVICE.create_temp_file_path(
            f"{uuid.uuid4()}.txt", temp_dir
        )
        parsed_doc = parsed_doc.replace("<br>", "\n")
        with open(file_path, "w", encoding="utf-8") as text_file:
            text_file.write(parsed_doc)
        durable_path = await asyncio.to_thread(get_asset_storage().publish_new, file_path, "uploads")
        response.append(
            DecomposedFileInfo(
                name=os.path.basename(other_files[index]), file_path=durable_path
            )
        )

    # Return the txt documents as it is
    for each_file in txt_files:
        source_reference = references[resolved_file_paths.index(each_file)]
        response.append(
            DecomposedFileInfo(name=os.path.basename(each_file), file_path=source_reference)
        )

    return response
