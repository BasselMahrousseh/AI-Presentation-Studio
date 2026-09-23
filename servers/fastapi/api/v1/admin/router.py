import csv
import io
import uuid
import os
import shutil
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    PublicUser,
)
from api.v1.auth.users import (
    PASSWORD_HELPER,
    get_current_admin,
    read_user_from_cookie,
    serialize_user,
)
from models.sql.generation_feedback import GenerationFeedback
from models.sql.user import User
from models.sql.key_value import KeyValueSqlModel
from services.database import get_async_session
from services.provider_settings import get_provider_settings, save_provider_settings
from services.presenton_cloud import get_presenton_provider, has_cloud_credentials
from utils.get_env import (
    get_app_data_directory_env,
    get_can_change_keys_env,
    get_temp_directory_env,
    get_presenton_oauth_issuer,
    is_disable_auth_enabled,
)
from utils.user_config import update_env_with_user_config


API_V1_ADMIN_ROUTER = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


async def require_settings_admin(
    request: Request,
    user: User | None = Depends(read_user_from_cookie),
) -> None:
    del request
    if is_disable_auth_enabled():
        return
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")


def _ensure_settings_are_mutable() -> None:
    if get_can_change_keys_env() == "false":
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to access this resource",
        )


@API_V1_ADMIN_ROUTER.get("/provider-settings")
async def read_provider_settings(
    _: None = Depends(require_settings_admin),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    _ensure_settings_are_mutable()
    settings = await get_provider_settings(session)
    provider = await get_presenton_provider(session, get_presenton_oauth_issuer())
    return {
        **settings,
        "PRESENTON_CONNECTED": has_cloud_credentials(provider),
        "PRESENTON_EMAIL": provider.email if provider is not None else None,
    }


@API_V1_ADMIN_ROUTER.put("/provider-settings")
async def update_provider_settings(
    config: dict[str, Any] = Body(...),
    _: None = Depends(require_settings_admin),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    _ensure_settings_are_mutable()
    saved = await save_provider_settings(session, config)
    update_env_with_user_config()
    return saved


@API_V1_ADMIN_ROUTER.get("/users", response_model=list[PublicUser])
async def list_users(
    _: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
):
    users = (
        await session.scalars(
            select(User).order_by(User.created_at.desc(), User.username.asc())
        )
    ).all()
    return [serialize_user(user) for user in users]


@API_V1_ADMIN_ROUTER.post(
    "/users", response_model=PublicUser, status_code=status.HTTP_201_CREATED
)
async def create_user(
    body: AdminCreateUserRequest,
    _: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
):
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(
            status_code=422,
            detail="Username must be at least 3 characters",
        )
    exists = await session.scalar(
        select(User.id).where(func.lower(User.username) == username.casefold())
    )
    if exists:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=username,
        hashed_password=PASSWORD_HELPER.hash(body.password),
        is_active=True,
        is_verified=True,
        is_superuser=False,
        auth_version=1,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return serialize_user(user)


@API_V1_ADMIN_ROUTER.put("/users/{user_id}/password", response_model=PublicUser)
async def reset_user_password(
    user_id: uuid.UUID,
    body: AdminResetPasswordRequest,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id or user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The primary administrator password is managed through deployment settings",
        )
    user.hashed_password = PASSWORD_HELPER.hash(body.password)
    user.auth_version += 1
    await session.commit()
    return serialize_user(user)


@API_V1_ADMIN_ROUTER.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_async_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id or user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The primary administrator account cannot be deleted",
        )
    await session.execute(
        delete(KeyValueSqlModel).where(
            KeyValueSqlModel.key == f"presentation_custom_themes:{user.id}"
        )
    )
    await session.delete(user)
    await session.commit()
    roots = (
        os.path.join(get_app_data_directory_env(), "images", "users"),
        os.path.join(get_app_data_directory_env(), "exports", "users"),
        os.path.join(get_app_data_directory_env(), "uploads", "users"),
        os.path.join(get_app_data_directory_env(), "pptx-to-html", "users"),
        os.path.join(get_app_data_directory_env(), "pptx-to-json", "users"),
        get_temp_directory_env() or "/tmp/presenton",
    )
    for root in roots:
        owned_dir = os.path.realpath(os.path.join(root, str(user_id)))
        root_dir = os.path.realpath(root)
        if owned_dir.startswith(f"{root_dir}{os.sep}") and os.path.isdir(owned_dir):
            shutil.rmtree(owned_dir)


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


@API_V1_ADMIN_ROUTER.get("/feedback", dependencies=[Depends(require_settings_admin)])
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
