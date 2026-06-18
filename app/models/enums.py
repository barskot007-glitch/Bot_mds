from enum import StrEnum


class EventStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    REGISTRATION_CLOSED = "registration_closed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class RegistrationStatus(StrEnum):
    REGISTERED = "registered"
    CANCELLED = "cancelled"
    ATTENDED = "attended"
    ABSENT = "absent"
    WAITING_LIST = "waiting_list"


class BroadcastStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RecipientStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    BLOCKED = "blocked"


class TicketStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WAITING_USER = "waiting_user"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AdminRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    SUPPORT = "support"


class FileType(StrEnum):
    PHOTO = "photo"
    DOCUMENT = "document"


class MessageAuthorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduledTaskType(StrEnum):
    BROADCAST = "broadcast"
    EVENT_PUBLICATION = "event_publication"
    EVENT_REMINDER = "event_reminder"
    REGISTRATION_CLOSE = "registration_close"
    CLEANUP = "cleanup"


class ScheduledTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
