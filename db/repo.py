from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from db.models import Base, Meeting, Setting, Status

engine = create_async_engine(config.DATABASE_URL)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def transition(
    s: AsyncSession, meeting_id: int, from_statuses: tuple[str, ...] | list[str], to_status: str
) -> bool:
    """Атомарная смена статуса. False => уже обработано в другом месте."""
    res = await s.execute(
        update(Meeting)
        .where(Meeting.id == meeting_id, Meeting.status.in_(from_statuses))
        .values(status=to_status, status_changed_at=datetime.now(timezone.utc))
    )
    await s.commit()
    return res.rowcount == 1


async def count_pending(s: AsyncSession, author_tg_id: int) -> int:
    q = select(func.count()).where(
        Meeting.author_tg_id == author_tg_id, Meeting.status == Status.PENDING)
    return (await s.execute(q)).scalar_one()


async def busy_meetings(s: AsyncSession, exclude_id: int | None = None) -> list[Meeting]:
    q = select(Meeting).where(Meeting.status.in_(Status.BUSY))
    if exclude_id is not None:
        q = q.where(Meeting.id != exclude_id)
    return list((await s.execute(q)).scalars())


async def get_meeting(s: AsyncSession, meeting_id: int) -> Meeting | None:
    return await s.get(Meeting, meeting_id)


async def get_setting(s: AsyncSession, key: str, default: str = "") -> str:
    row = await s.get(Setting, key)
    return row.value if row else default


async def set_setting(s: AsyncSession, key: str, value: str) -> None:
    row = await s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))
    await s.commit()


async def finalize_approval(
    s: AsyncSession, meeting_id: int, *, zoom_id: str, join_url: str, passcode: str,
    caldav_uid: str, caldav_href: str,
) -> bool:
    """pending -> approved одним UPDATE вместе со всеми внешними ID.
    False => статус уже изменился (например, автор отозвал заявку)."""
    res = await s.execute(
        update(Meeting)
        .where(Meeting.id == meeting_id, Meeting.status == Status.PENDING)
        .values(status=Status.APPROVED, status_changed_at=datetime.now(timezone.utc),
                zoom_meeting_id=zoom_id, zoom_join_url=join_url, zoom_passcode=passcode,
                caldav_uid=caldav_uid, caldav_href=caldav_href)
    )
    await s.commit()
    return res.rowcount == 1


async def active_meetings(s: AsyncSession) -> list[Meeting]:
    q = select(Meeting).where(Meeting.status.in_(Status.ACTIVE))
    return list((await s.execute(q)).scalars())


async def user_visible_meetings(s: AsyncSession, tg_id: int) -> list[Meeting]:
    since = datetime.now(timezone.utc) - timedelta(days=config.REJECTED_VISIBLE_DAYS)
    q = select(Meeting).where(
        Meeting.author_tg_id == tg_id,
        or_(Meeting.status.in_(Status.ACTIVE),
            and_(Meeting.status == Status.REJECTED, Meeting.status_changed_at > since)),
    )
    return list((await s.execute(q)).scalars())


async def set_admin_msgs(s: AsyncSession, meeting_id: int, msgs: list[dict]) -> None:
    await s.execute(update(Meeting).where(Meeting.id == meeting_id).values(admin_msgs=msgs))
    await s.commit()
