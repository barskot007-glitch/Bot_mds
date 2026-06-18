from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_values
from app.models.enums import (
    BroadcastStatus,
    FileType,
    MessageAuthorType,
    RecipientStatus,
    TicketStatus,
)

if TYPE_CHECKING:
    from app.models.users_events import User


class Broadcast(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "broadcasts"
    __table_args__ = (
        Index("ix_broadcasts_status", "status"),
        Index("ix_broadcasts_scheduled_at", "scheduled_at"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str] = mapped_column(String(16), default="HTML", nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    audience_filter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[BroadcastStatus] = mapped_column(
        Enum(BroadcastStatus, values_callable=enum_values, native_enum=False),
        default=BroadcastStatus.DRAFT,
        nullable=False,
    )
    author_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    total_recipients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    files: Mapped[list[BroadcastFile]] = relationship(
        back_populates="broadcast", cascade="all, delete-orphan", order_by="BroadcastFile.position"
    )
    buttons: Mapped[list[BroadcastButton]] = relationship(
        back_populates="broadcast",
        cascade="all, delete-orphan",
        order_by="BroadcastButton.position",
    )
    recipients: Mapped[list[BroadcastRecipient]] = relationship(back_populates="broadcast")


class BroadcastFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "broadcast_files"

    broadcast_id: Mapped[str] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True
    )
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

    broadcast: Mapped[Broadcast] = relationship(back_populates="files")


class BroadcastButton(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "broadcast_buttons"

    broadcast_id: Mapped[str] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))
    callback_key: Mapped[str | None] = mapped_column(String(64))
    is_details: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    broadcast: Mapped[Broadcast] = relationship(back_populates="buttons")


class BroadcastRecipient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "broadcast_recipients"
    __table_args__ = (
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_recipient"),
        Index("ix_broadcast_recipients_status", "broadcast_id", "status"),
    )

    broadcast_id: Mapped[str] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[RecipientStatus] = mapped_column(
        Enum(RecipientStatus, values_callable=enum_values, native_enum=False),
        default=RecipientStatus.PENDING,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    broadcast: Mapped[Broadcast] = relationship(back_populates="recipients")
    user: Mapped["User"] = relationship()  # noqa: UP037


class SupportTicket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_status", "status"),
        Index("ix_support_tickets_user", "user_id"),
    )

    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, values_callable=enum_values, native_enum=False),
        default=TicketStatus.NEW,
        nullable=False,
    )
    assigned_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="tickets")  # noqa: UP037
    messages: Mapped[list[SupportMessage]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="SupportMessage.created_at"
    )


class SupportMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_messages"

    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True
    )
    author_type: Mapped[MessageAuthorType] = mapped_column(
        Enum(MessageAuthorType, values_callable=enum_values, native_enum=False), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    admin_id: Mapped[str | None] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(Text)

    ticket: Mapped[SupportTicket] = relationship(back_populates="messages")
    attachments: Mapped[list[SupportAttachment]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class SupportAttachment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_attachments"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("support_messages.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str | None] = mapped_column(String(512))
    file_unique_id: Mapped[str | None] = mapped_column(String(512))
    file_type: Mapped[FileType | None] = mapped_column(
        Enum(FileType, values_callable=enum_values, native_enum=False)
    )
    file_name: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[int | None] = mapped_column(BigInteger)
    caption: Mapped[str | None] = mapped_column(String(1024))
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    url: Mapped[str | None] = mapped_column(String(2048))

    message: Mapped[SupportMessage] = relationship(back_populates="attachments")
