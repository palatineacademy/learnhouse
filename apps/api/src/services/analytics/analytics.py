import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_background_tasks: set = set()


async def track(
    event_name: str,
    org_id: int,
    user_id: int = 0,
    session_id: str = "",
    properties: dict | None = None,
    source: str = "api",
    ip: str = "",
) -> None:
    """Fire-and-forget analytics event to PostgreSQL.
    All errors are swallowed — analytics never breaks the app.
    """
    task = asyncio.create_task(
        _send_event(
            event_name=event_name,
            org_id=org_id,
            user_id=user_id,
            session_id=session_id,
            properties=properties or {},
            source=source,
            ip=ip,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _send_event(
    event_name: str,
    org_id: int,
    user_id: int,
    session_id: str,
    properties: dict,
    source: str,
    ip: str,
) -> None:
    try:
        from sqlalchemy import text
        from src.core.events.database import engine

        async with engine.connect() as conn:
            await conn.execute(
                text("""
                    INSERT INTO analytics_events
                        (event_name, timestamp, org_id, user_id, session_id, properties, source, ip)
                    VALUES
                        (:event_name, :timestamp, :org_id, :user_id, :session_id, CAST(:properties AS jsonb), :source, :ip)
                """),
                {
                    "event_name": event_name,
                    "timestamp": datetime.now(timezone.utc),
                    "org_id": org_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "properties": json.dumps(properties),
                    "source": source,
                    "ip": ip,
                },
            )
            await conn.commit()
    except Exception:
        logger.warning("Failed to send analytics event %s", event_name, exc_info=True)
