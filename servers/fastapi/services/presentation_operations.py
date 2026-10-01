"""Idempotent create outcomes; no network work or independent commit here."""
import hashlib
import json
import re
import uuid

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from models.sql.presentation import PresentationModel
from models.sql.presentation_operation import PresentationOperation


def validate_operation_id(value: str | None) -> str | None:
    if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise HTTPException(400, "Invalid operation identity")
    return value


def operation_key(owner_id: uuid.UUID, operation_id: str) -> str:
    return hashlib.sha256(f"{owner_id}:{operation_id}".encode()).hexdigest()


def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


async def find_operation(session, owner_id: uuid.UUID, operation_id: str):
    row = await session.get(PresentationOperation, operation_key(owner_id, operation_id))
    return row if row and row.owner_id == owner_id else None


async def replay_operation(session, owner_id, operation_id, fingerprint):
    row = await find_operation(session, owner_id, operation_id)
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise HTTPException(409, "Operation identity was already used for different input")
    deck = await session.get(PresentationModel, row.presentation_id)
    if deck is None or deck.owner_id != owner_id:
        raise HTTPException(410, "Operation completed but the presentation is no longer available")
    return deck


async def commit_presentation(session, presentation, owner_id, operation_id, fingerprint):
    session.add(presentation)
    if operation_id:
        session.add(PresentationOperation(operation_key=operation_key(owner_id, operation_id), operation_id=operation_id,
                                         owner_id=owner_id, request_hash=fingerprint, presentation_id=presentation.id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if operation_id:
            winner = await replay_operation(session, owner_id, operation_id, fingerprint)
            if winner is not None:
                return winner
        raise
    return presentation
