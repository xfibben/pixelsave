from redis import Redis
from rq import Queue

from app.config import get_settings


def get_redis_connection() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url)


def get_queue() -> Queue:
    settings = get_settings()
    return Queue(
        name=settings.queue_name,
        connection=get_redis_connection(),
        default_timeout=settings.yt_dlp_timeout_seconds,
    )

