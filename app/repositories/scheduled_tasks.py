from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_audit import ScheduledTask
from app.models.enums import ScheduledTaskStatus, ScheduledTaskType


class ScheduledTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_update(
        self,
        *,
        task_type: ScheduledTaskType,
        run_at: datetime,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ScheduledTask:
        task = await self.session.scalar(
            select(ScheduledTask).where(ScheduledTask.idempotency_key == idempotency_key)
        )
        if task is None:
            task = ScheduledTask(
                task_type=task_type,
                run_at=run_at,
                payload=payload,
                idempotency_key=idempotency_key,
                status=ScheduledTaskStatus.PENDING,
            )
            self.session.add(task)
        else:
            task.run_at = run_at
            task.payload = payload
            task.status = ScheduledTaskStatus.PENDING
            task.error_message = None
        await self.session.flush()
        return task

    async def due(self, now: datetime, limit: int = 100) -> list[ScheduledTask]:
        return list(
            await self.session.scalars(
                select(ScheduledTask)
                .where(
                    ScheduledTask.status.in_(
                        [ScheduledTaskStatus.PENDING, ScheduledTaskStatus.FAILED]
                    ),
                    ScheduledTask.run_at <= now,
                )
                .order_by(ScheduledTask.run_at.asc())
                .limit(limit)
            )
        )
