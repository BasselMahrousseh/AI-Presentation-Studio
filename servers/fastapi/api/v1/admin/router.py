import csv
import io
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.sql.generation_feedback import GenerationFeedback
from models.sql.user import User
from services.database import get_async_session
from utils.get_env import (
    is_disable_auth_enabled,
)


API_V1_ADMIN_ROUTER = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


async def require_service_admin(request: Request) -> None:
    """The admin surface is for the Workspace backend's service key (no X-On-Behalf-Of).
    SessionAuthMiddleware already enforces this; the check is repeated here so the route
    never relies on middleware ordering. DISABLE_AUTH (local development) allows it."""
    if is_disable_auth_enabled():
        return
    principal = getattr(request.state, "auth_principal", None)
    if principal is None or not principal.is_admin:
        raise HTTPException(status_code=403, detail="Forbidden")


FEEDBACK_EXPORT_COLUMNS = (
    "created_at",
    "updated_at",
    "stage",
    "rating",
    "reasons",
    "comment",
    "username",
    "external_subject",
    "presentation_id",
    "source_presentation_id",
    "generation_id",
    "generation_mode",
    "smart_template",
    "slide_count",
    "language",
    "outline_hash",
)


def _feedback_export_row(row: GenerationFeedback, user: User | None) -> dict[str, Any]:
    context = row.context or {}
    return {
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "stage": row.stage,
        "rating": row.rating,
        "reasons": row.reasons or [],
        "comment": row.comment,
        "username": user.username if user else None,
        "external_subject": user.external_subject if user else None,
        "presentation_id": str(row.presentation_id) if row.presentation_id else None,
        # From the rating-time snapshot, so it survives the source being deleted.
        "source_presentation_id": context.get("source_presentation_id"),
        "generation_id": str(row.generation_id),
        "generation_mode": context.get("generation_mode"),
        "smart_template": context.get("smart_template"),
        "slide_count": context.get("slide_count"),
        "language": context.get("language"),
        "outline_hash": context.get("outline_hash"),
    }


def _feedback_summary(rows: list[GenerationFeedback]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for stage in ("outline", "deck"):
        stage_rows = [row for row in rows if row.stage == stage]
        up = sum(1 for row in stage_rows if row.rating > 0)
        reasons: dict[str, int] = {}
        by_mode: dict[str, dict[str, int]] = {}
        for row in stage_rows:
            for reason in row.reasons or []:
                reasons[reason] = reasons.get(reason, 0) + 1
            mode = (row.context or {}).get("smart_template") or (
                row.context or {}
            ).get("generation_mode") or "unknown"
            bucket = by_mode.setdefault(mode, {"up": 0, "down": 0})
            bucket["up" if row.rating > 0 else "down"] += 1
        summary[stage] = {
            "total": len(stage_rows),
            "up": up,
            "down": len(stage_rows) - up,
            "up_rate": round(up / len(stage_rows), 3) if stage_rows else None,
            "top_reasons": dict(
                sorted(reasons.items(), key=lambda item: item[1], reverse=True)
            ),
            "by_mode": by_mode,
        }
    return summary


@API_V1_ADMIN_ROUTER.get("/feedback", dependencies=[Depends(require_service_admin)])
async def list_generation_feedback(
    stage: Literal["outline", "deck"] | None = None,
    format: Literal["json", "csv"] = "json",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_async_session),
):
    """Every user's outline/deck ratings, newest first, plus up/down totals and top reasons.

    The summary covers all rows matching `stage`; `offset`/`limit` only page the item list.
    `format=csv` returns every matching row as a CSV download instead.
    """
    statement = (
        select(GenerationFeedback, User)
        .outerjoin(User, User.id == GenerationFeedback.owner_id)
        .order_by(GenerationFeedback.updated_at.desc())
        # Admin view spans every owner.
        .execution_options(skip_owner_scope=True)
    )
    if stage:
        statement = statement.where(GenerationFeedback.stage == stage)
    results = (await session.execute(statement)).all()

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=FEEDBACK_EXPORT_COLUMNS)
        writer.writeheader()
        for row, user in results:
            record = _feedback_export_row(row, user)
            record["reasons"] = ";".join(record["reasons"])
            writer.writerow(record)
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="generation_feedback.csv"'
            },
        )

    return {
        "summary": _feedback_summary([row for row, _ in results]),
        "total": len(results),
        "items": [
            _feedback_export_row(row, user)
            for row, user in results[offset : offset + limit]
        ],
    }
