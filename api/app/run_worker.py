from rq import Worker

from app.config import get_settings
from app.queue import get_redis_connection
from app.storage import ensure_bucket


def main() -> None:
    settings = get_settings()
    ensure_bucket()
    connection = get_redis_connection()
    worker = Worker([settings.queue_name], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
