from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config.settings import Settings
from app.models import Base
from app.models.enums import EventStatus
from app.models.users_events import Event, User
from app.utils.time import utcnow


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        BOT_TOKEN="123456:TESTTOKEN",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        APP_ENV="test",
        RATE_LIMIT_SECONDS=0,
        TRACKING_BASE_URL="https://example.test",
    )


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as value:
        yield value
        await value.rollback()


async def make_user(
    session: AsyncSession,
    telegram_id: int = 1001,
    *,
    country: str = "Армения",
    age_group: str = "25-34",
    subscribed: bool = True,
) -> User:
    now = utcnow()
    user = User(
        telegram_id=telegram_id,
        username=f"user{telegram_id}",
        first_name="Test",
        language_code="ru",
        country=country,
        age=30,
        age_group=age_group,
        registered_at=now,
        last_activity_at=now,
        is_subscribed=subscribed,
        data_processing_consent=True,
        registration_completed=True,
    )
    session.add(user)
    await session.flush()
    return user


async def make_event(
    session: AsyncSession,
    *,
    title: str = "Тестовое мероприятие",
    capacity: int | None = None,
    status: EventStatus = EventStatus.PUBLISHED,
) -> Event:
    event = Event(
        title=title,
        short_description="Краткое описание",
        full_description="Полное описание",
        start_at=utcnow() + timedelta(days=2),
        end_at=utcnow() + timedelta(days=2, hours=2),
        timezone="Asia/Yerevan",
        capacity=capacity,
        registration_enabled=True,
        status=status,
    )
    session.add(event)
    await session.flush()
    return event
