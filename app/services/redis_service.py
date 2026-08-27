import redis # type: ignore

from app.config import(
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_TTL
)

class RedisService:
    def __init__(self):
        self.client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
        )

    def ping(self) -> bool:
        return bool(self.client.ping())

    def get(self, key:str) -> str | None:
        return self.client.get(key)

    def set(self, key:str, value:str, ttl: int | None = None ) -> None:
        self.client.setex(
            key,
            ttl or REDIS_TTL,
            value,
        )

    def delete(self, key:str) -> None:
        self.client.delete(key)

redis_service = RedisService()