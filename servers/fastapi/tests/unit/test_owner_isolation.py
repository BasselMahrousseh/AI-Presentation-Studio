import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.v1.auth.context import reset_current_owner_id, set_current_owner_id
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.user import User
from services import database as _database_events  # noqa: F401


def test_owned_queries_are_isolated_per_owner():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
            await connection.run_sync(PresentationModel.__table__.create)

        first_id, second_id = uuid.uuid4(), uuid.uuid4()
        async with session_maker() as session:
            session.add_all(
                [
                    User(
                        id=first_id,
                        username="first",
                        hashed_password="unused",
                        is_active=True,
                        is_superuser=False,
                        is_verified=True,
                    ),
                    User(
                        id=second_id,
                        username="second",
                        hashed_password="unused",
                        is_active=True,
                        is_superuser=False,
                        is_verified=True,
                    ),
                    PresentationModel(
                        owner_id=first_id,
                        version=PresentationVersion.V2_STANDARD,
                        content="first",
                        n_slides=1,
                        language="English",
                    ),
                    PresentationModel(
                        owner_id=second_id,
                        version=PresentationVersion.V2_STANDARD,
                        content="second",
                        n_slides=1,
                        language="English",
                    ),
                ]
            )
            await session.commit()

        context_token = set_current_owner_id(first_id)
        try:
            async with session_maker() as session:
                presentations = (
                    await session.scalars(select(PresentationModel))
                ).all()
        finally:
            reset_current_owner_id(context_token)
            await engine.dispose()

        assert [item.content for item in presentations] == ["first"]

    asyncio.run(run())
