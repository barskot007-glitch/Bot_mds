from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_values
from app.models.enums import AdminRole, NotificationStatus, ScheduledTaskStatus, ScheduledTaskType


class SequenceCounter(Base):
    """Атомарный счётчик для человекочитаемых последовательных номеров."""

    __tablename__ = "sequence_counters"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class FAQ(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "faq"
    __table_args__ = (Index("ix_faq_published_position", "is_published", "position"),)

    question: Mapped[str] = mapped_column(String(512), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BotText(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "bot_texts"
    __table_args__ = (
        Index("ix_bot_texts_key_active_position", "text_key", "is_active", "position"),
    )

    text_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )


class Admin(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "admins"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, values_callable=enum_values, native_enum=False), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    added_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_status_scheduled", "status", "scheduled_at"),)

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    broadcast_id: Mapped[str | None] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, values_callable=enum_values, native_enum=False),
        default=NotificationStatus.PENDING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class Log(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "logs"
    __table_args__ = (Index("ix_logs_created_level", "created_at", "level"),)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    logger: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class UserAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_actions"
    __table_args__ = (Index("ix_user_actions_user_created", "user_id", "created_at"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdminAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "admin_actions"
    __table_args__ = (Index("ix_admin_actions_admin_created", "admin_id", "created_at"),)

    admin_id: Mapped[str] = mapped_column(
        ForeignKey("admins.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrackingLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tracking_links"
    __table_args__ = (
        UniqueConstraint("token", name="uq_tracking_links_token"),
        Index("ix_tracking_links_broadcast", "broadcast_id"),
    )

    token: Mapped[str] = mapped_column(String(64), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    broadcast_id: Mapped[str | None] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE")
    )
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    button_id: Mapped[str | None] = mapped_column(
        ForeignKey("broadcast_buttons.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LinkClick(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "link_clicks"
    __table_args__ = (Index("ix_link_clicks_tracking_clicked", "tracking_link_id", "clicked_at"),)

    tracking_link_id: Mapped[str] = mapped_column(
        ForeignKey("tracking_links.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    broadcast_id: Mapped[str | None] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="SET NULL")
    )
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    button_id: Mapped[str | None] = mapped_column(
        ForeignKey("broadcast_buttons.id", ondelete="SET NULL")
    )
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class ScheduledTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_scheduled_tasks_idempotency"),
        Index("ix_scheduled_tasks_due", "status", "run_at"),
    )

    task_type: Mapped[ScheduledTaskType] = mapped_column(
        Enum(ScheduledTaskType, values_callable=enum_values, native_enum=False), nullable=False
    )
    status: Mapped[ScheduledTaskStatus] = mapped_column(
        Enum(ScheduledTaskStatus, values_callable=enum_values, native_enum=False),
        default=ScheduledTaskStatus.PENDING,
        nullable=False,
    )
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
