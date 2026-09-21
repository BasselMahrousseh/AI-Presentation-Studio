import asyncio
import json
import stat

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.v1.auth import bootstrap
from api.v1.auth.users import PASSWORD_HELPER
from models.sql.access_token import AccessToken
from models.sql.user import User


async def _create_auth_database(database_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(User.__table__.create)
        await connection.run_sync(AccessToken.__table__.create)
    return engine, session_maker


def test_reset_auth_recovers_admin_without_replacing_account(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "userConfig.json"
    config_path.write_text(
        json.dumps(
            {
                "AUTH_USERNAME": "old-admin",
                "AUTH_PASSWORD_HASH": "old-hash",
                "AUTH_SECRET_KEY": "old-secret",
                "LLM_PROVIDER": "openai",
            }
        )
    )
    monkeypatch.setenv("USER_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("RESET_AUTH", "true")
    monkeypatch.setenv("AUTH_USERNAME", "recovered-admin")
    monkeypatch.setenv("AUTH_PASSWORD", "new-secret-123")
    monkeypatch.delenv("AUTH_OVERRIDE_FROM_ENV", raising=False)

    async def runner():
        engine, session_maker = await _create_auth_database(tmp_path / "auth.db")
        original_id = None
        try:
            async with session_maker() as session:
                admin = User(
                    username="old-admin",
                    hashed_password=PASSWORD_HELPER.hash("old-secret-123"),
                    is_active=True,
                    is_verified=True,
                    is_superuser=True,
                    auth_version=4,
                )
                session.add(admin)
                await session.flush()
                original_id = admin.id
                session.add(AccessToken(token="sk-presenton-old", user_id=admin.id))
                await session.commit()

            async def skip_ownership_backfill(_session, _admin):
                return None

            monkeypatch.setattr(bootstrap, "async_session_maker", session_maker)
            monkeypatch.setattr(
                bootstrap,
                "_backfill_legacy_ownership",
                skip_ownership_backfill,
            )
            await bootstrap.bootstrap_database_admin()

            async with session_maker() as session:
                recovered = await session.scalar(select(User))
                tokens = list(await session.scalars(select(AccessToken)))

            assert recovered is not None
            assert recovered.id == original_id
            assert recovered.username == "recovered-admin"
            assert recovered.admin_slot == "primary"
            assert recovered.auth_version == 5
            verified, _ = PASSWORD_HELPER.verify_and_update(
                "new-secret-123",
                recovered.hashed_password,
            )
            assert verified is True
            assert tokens == []
        finally:
            await engine.dispose()

    asyncio.run(runner())

    config = json.loads(config_path.read_text())
    assert config["AUTH_USERNAME"] == "recovered-admin"
    assert config["AUTH_PASSWORD_HASH"] != "old-hash"
    assert config["AUTH_SECRET_KEY"] != "old-secret"
    assert config["LLM_PROVIDER"] == "openai"
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "userConfig.json.bak").stat().st_mode) == 0o600


def test_reset_auth_without_password_refuses_to_delete_or_replace_admin(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("USER_CONFIG_PATH", str(tmp_path / "userConfig.json"))
    monkeypatch.setenv("RESET_AUTH", "true")
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("AUTH_OVERRIDE_FROM_ENV", raising=False)

    async def runner():
        engine, session_maker = await _create_auth_database(
            tmp_path / "missing-password.db"
        )
        try:
            async with session_maker() as session:
                admin = User(
                    username="admin",
                    hashed_password=PASSWORD_HELPER.hash("old-secret-123"),
                    is_active=True,
                    is_verified=True,
                    is_superuser=True,
                    auth_version=1,
                )
                session.add(admin)
                await session.commit()
                original_id = admin.id

            monkeypatch.setattr(bootstrap, "async_session_maker", session_maker)
            with pytest.raises(RuntimeError, match="require AUTH_PASSWORD"):
                await bootstrap.bootstrap_database_admin()

            async with session_maker() as session:
                users = list(await session.scalars(select(User)))
            assert len(users) == 1
            assert users[0].id == original_id
            assert users[0].username == "admin"
        finally:
            await engine.dispose()

    asyncio.run(runner())


def _bootstrap_with_users(monkeypatch, tmp_path, users):
    for name in ("RESET_AUTH", "AUTH_OVERRIDE_FROM_ENV", "AUTH_USERNAME", "AUTH_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("USER_CONFIG_PATH", str(tmp_path / "userConfig.json"))

    async def runner():
        engine, session_maker = await _create_auth_database(tmp_path / "auth.db")
        try:
            async with session_maker() as session:
                session.add_all(users)
                await session.commit()
            monkeypatch.setattr(bootstrap, "async_session_maker", session_maker)
            await bootstrap.bootstrap_database_admin()
        finally:
            await engine.dispose()

    asyncio.run(runner())


def test_workspace_only_database_restarts_without_a_bootstrap_admin(monkeypatch, tmp_path):
    # Workspace accounts are created on first login and never have a password or admin role.
    _bootstrap_with_users(
        monkeypatch,
        tmp_path,
        [
            User(
                username="ws:alice-1a2b3c4d",
                external_subject="alice",
                hashed_password="!external",
                is_active=True,
                is_verified=True,
                is_superuser=False,
            )
        ],
    )


def test_local_accounts_without_an_admin_still_refuse_to_start(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="no bootstrap administrator"):
        _bootstrap_with_users(
            monkeypatch,
            tmp_path,
            [
                User(
                    username="local-user",
                    hashed_password=PASSWORD_HELPER.hash("some-password-1"),
                    is_active=True,
                    is_verified=True,
                    is_superuser=False,
                )
            ],
        )
