import unittest

from app.conversation.models import ConversationContext, SalesStage
from app.conversation.redis_context import RedisConversationContextStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def expire(self, key: str, ttl: int) -> bool:
        if key not in self.values:
            return False
        self.expirations[key] = ttl
        return True

    def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        return int(existed)

    def scan_iter(self, match: str, count: int = 10):
        prefix = match.removesuffix("*")
        yield from [key for key in self.values if key.startswith(prefix)]

    def ttl(self, key: str) -> int:
        return self.expirations.get(key, -1) if key in self.values else -2


class RedisConversationContextStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.store = RedisConversationContextStore(self.redis)
        self.store.prefix = "test:conversation"
        self.store.ttl = 600

    def test_save_and_load_complete_conversation_context(self) -> None:
        context = ConversationContext(
            session_id="session-1",
            channel="web",
            latest_product_code="G81V6",
            sales_stage=SalesStage.COLLECTING_PRODUCT,
            draft_color="Đen",
            draft_size="36",
            draft_quantity=1,
            cart_items=[{
                "product_code": "G81V6",
                "color": "Đen",
                "size": "36",
                "quantity": 1,
            }],
        )
        self.store.append(context, "user", "Lấy một đôi màu đen size 36")
        self.store.save(context)

        loaded = self.store.get("session-1", "WEB")

        self.assertEqual(loaded.latest_product_code, "G81V6")
        self.assertEqual(loaded.draft_color, "Đen")
        self.assertEqual(loaded.draft_size, "36")
        self.assertEqual(loaded.cart_items[0]["quantity"], 1)
        self.assertEqual(loaded.history[0].role, "user")
        self.assertEqual(
            self.redis.expirations["test:conversation:web:session-1"],
            600,
        )

    def test_missing_session_returns_new_context(self) -> None:
        context = self.store.get("new-session", "Web")

        self.assertEqual(context.session_id, "new-session")
        self.assertEqual(context.channel, "web")
        self.assertEqual(context.cart_items, [])

    def test_reset_deletes_session(self) -> None:
        context = ConversationContext(session_id="session-2", channel="web")
        self.store.save(context)

        self.store.reset("session-2", "web")

        self.assertNotIn("test:conversation:web:session-2", self.redis.values)

    def test_channels_are_isolated(self) -> None:
        web = ConversationContext(
            session_id="same-id",
            channel="web",
            latest_product_code="FE04",
        )
        telegram = ConversationContext(
            session_id="same-id",
            channel="telegram",
            latest_product_code="TM32",
        )
        self.store.save(web)
        self.store.save(telegram)

        self.assertEqual(
            self.store.get("same-id", "web").latest_product_code,
            "FE04",
        )
        self.assertEqual(
            self.store.get("same-id", "telegram").latest_product_code,
            "TM32",
        )

    def test_admin_can_list_inspect_and_delete_sessions(self) -> None:
        context = ConversationContext(
            session_id="telegram-user-1",
            channel="telegram",
            draft_customer_name="Minh",
        )
        self.store.append(context, "user", "Cho tôi xem sản phẩm")
        self.store.save(context)

        sessions = self.store.list_sessions()
        detail = self.store.inspect("telegram-user-1", "telegram")

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["customer_name"], "Minh")
        self.assertEqual(sessions[0]["message_count"], 1)
        self.assertEqual(detail["context"]["history"][0]["role"], "user")

        self.store.reset("telegram-user-1", "telegram")
        self.assertIsNone(self.store.inspect("telegram-user-1", "telegram"))


if __name__ == "__main__":
    unittest.main()
