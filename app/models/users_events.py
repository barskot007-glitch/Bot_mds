from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_values
from app.models.enums import EventStatus, FileType, RegistrationStatus

if TYPE_CHECKING:
    from app.models.broadcast_support import SupportTicket


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_country", "country"),
        Index("ix_users_age_group", "age_group"),
        Index("ix_users_registered_at", "registered_at"),
        Index("ix_users_last_activity_at", "last_activity_at"),
        Index("ix_users_is_subscribed", "is_subscribed"),
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str | None] = mapped_column(String(128))
    birth_date: Mapped[date | None] = mapped_column(Date)
    age: Mapped[int | None] = mapped_column(Integer)
    age_group: Mapped[str | None] = mapped_column(String(32))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str | None] = mapped_column(String(255))
    notifications_consent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data_processing_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registration_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    participation_history: Mapped[str | None] = mapped_column(Text)

    registrations: Mapped[list[Registration]] = relationship(back_populates="user")
    tickets: Mapped[list["SupportTicket"]] = relationship(back_populates="user")  # noqa: UP037


class Event(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_status", "status"),
        Index("ix_events_start_at", "start_at"),
        Index("ix_events_published_at", "published_at"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(1024))
    full_description: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    country: Mapped[str | None] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(128))
    address: Mapped[str | None] = mapped_column(String(512))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    map_url: Mapped[str | None] = mapped_column(String(2048))
    details_url: Mapped[str | None] = mapped_column(String(2048))
    capacity: Mapped[int | None] = mapped_column(Integer)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    registration_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, values_callable=enum_values, native_enum=False),
        default=EventStatus.DRAFT,
        nullable=False,
    )
    author_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files: Mapped[list[EventFile]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="EventFile.position"
    )
    links: Mapped[list[EventLink]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="EventLink.position"
    )
    registrations: Mapped[list[Registration]] = relationship(back_populates="event")
    reminders: Mapped[list[EventReminder]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_files"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_unique_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[FileType] = mapped_column(
        Enum(FileType, values_callable=enum_values, native_enum=False), nullable=False
    )
    file_name: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[int | None] = mapped_column(BigInteger)
    caption: Mapped[str | None] = mapped_column(String(1024))
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    event: Mapped[Event] = relationship(back_populates="files")


class EventLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_links"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_details: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    event: Mapped[Event] = relationship(back_populates="links")


class Registration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_registrations_user_event"),
        Index("ix_registrations_user_event", "user_id", "event_id"),
        Index("ix_registrations_status", "status"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), nullable=False
    )
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus, values_callable=enum_values, native_enum=False),
        default=RegistrationStatus.REGISTERED,
        nullable=False,
    )
    source: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attended: Mapped[bool | None] = mapped_column(Boolean)
    attendance_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_comment: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="registrations")
    event: Mapped[Event] = relationship(back_populates="registrations")


class EventView(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "event_views"
    __table_args__ = (
        Index("ix_event_views_event_user", "event_id", "user_id"),
        Index("ix_event_views_viewed_at", "viewed_at"),
    )

    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventReminder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_reminders"
    __table_args__ = (
        UniqueConstraint("event_id", "minutes_before", name="uq_event_reminder_offset"),
    )

    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    minutes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event: Mapped[Event] = relationship(back_populates="reminders")
