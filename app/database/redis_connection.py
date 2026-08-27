import os
from pathlib import Path

from dotenv import load_dotenv  # type: ignore
from redis import Redis  # type: ignore
from redis.exceptions import RedisError  # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://127.0.0.1:6379/0",
)
REDIS_SOCKET_TIMEOUT_SECONDS = float(
    os.getenv("REDIS_SOCKET_TIMEOUT_SECONDS", "15")
)


def create_redis_client() -> Redis:
    return Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        health_check_interval=30,
    )

redis_client = create_redis_client()


def check_redis_connection() -> bool:
    try:
        return bool(redis_client.ping())
    except RedisError:
        return False
