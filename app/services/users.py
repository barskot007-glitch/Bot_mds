from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.models.users_events import User
from app.repositories.users import UserRepository
from app.utils.validators import validate_age


@dataclass(frozen=True, slots=True)
class AgeGroup:
    minimum: int
    maximum: int
    label: str


def parse_age_groups(config: str) -> tuple[AgeGroup, ...]:
    groups: list[AgeGroup] = []
    for item in config.split(","):
        range_part, label = item.split(":", maxsplit=1)
        minimum, maximum = (int(value) for value in range_part.split("-", maxsplit=1))
        groups.append(AgeGroup(minimum, maximum, label.strip()))
    groups.sort(key=lambda group: group.minimum)
    return tuple(groups)


def determine_age_group(age: int, config: str) -> str:
    validate_age(age)
    for group in parse_age_groups(config):
        if group.minimum <= age <= group.maximum:
            return group.label
    raise ValueError("Для указанного возраста не настроена возрастная группа")


class UserService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.repository = UserRepository(session)
        self.settings = settings

    async def ensure_user(
        self,
        telegram_user: TelegramUser,
        *,
        now: datetime,
        source: str | None = None,
    ) -> User:
        return await self.repository.create_or_update_telegram_profile(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            language_code=telegram_user.language_code,
            now=now,
            source=source,
        )

    async def complete_registration(
        self,
        user: User,
        *,
        country: str,
        age: int,
        notifications_consent: bool,
        data_processing_consent: bool,
    ) -> User:
        if not data_processing_consent:
            raise ValueError("Для регистрации необходимо согласие на обработку данных")
        age_group = determine_age_group(age, self.settings.age_groups)
        return await self.repository.complete_registration(
            user,
            country=country.strip(),
            age=validate_age(age),
            age_group=age_group,
            notifications_consent=notifications_consent,
            data_processing_consent=data_processing_consent,
        )
