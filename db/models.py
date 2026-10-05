from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Хранит UTC (naive в БД), отдаёт aware-datetime в UTC."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime запрещён")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Status:
    PENDING = "pending"
    APPROVED = "approved"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"

    LABELS = {
        PENDING: "на рассмотрении",
        APPROVED: "одобрена",
        CANCEL_REQUESTED: "отмена запрошена",
        CANCELLED: "отменена",
        REJECTED: "отклонена",
        WITHDRAWN: "отменена автором",
    }
    BUSY = (APPROVED, CANCEL_REQUESTED)
    ACTIVE = (PENDING, APPROVED, CANCEL_REQUESTED)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    author_name: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(300))
    committee: Mapped[str] = mapped_column(String(300))
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    duration_min: Mapped[int] = mapped_column(Integer)
    is_recurring: Mapped[bool] = mapped_column(default=False)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weeks_of_month: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=Status.PENDING, index=True)
    status_changed_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc))
    zoom_meeting_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    zoom_join_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    zoom_passcode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    caldav_uid: Mapped[str | None] = mapped_column(String(200), nullable=True)
    caldav_href: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_msgs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
