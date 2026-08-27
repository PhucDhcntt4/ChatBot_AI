import unittest
from unittest.mock import patch

from app.database.conversation_repository import ConversationRepository


class _Cursor:
    def __init__(self, *, one=None, all_rows=None, rowcount=1):
        self._one = one
        self._all = all_rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Connection:
    def __init__(self, cursors):
        self.cursors = list(cursors)
        self.calls = []

    def execute(self, sql, parameters=()):
        self.calls.append((sql, parameters))
        return self.cursors.pop(0)


class _ConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class ConversationRepositoryTests(unittest.TestCase):
    def test_ensure_session_returns_database_id(self):
        connection = _Connection([_Cursor(one={"id": 17})])
        with patch(
            "app.database.conversation_repository.database_connection",
            return_value=_ConnectionContext(connection),
        ):
            result = ConversationRepository().ensure_session(
                channel="Telegram",
                session_key="1481483387",
                external_user_id="1481483387",
            )

        self.assertEqual(result, 17)
        self.assertEqual(connection.calls[0][1][0], "telegram")

    def test_save_message_returns_none_for_duplicate_external_id(self):
        connection = _Connection([_Cursor(one=None)])
        with patch(
            "app.database.conversation_repository.database_connection",
            return_value=_ConnectionContext(connection),
        ):
            result = ConversationRepository().save_message(
                conversation_id=17,
                channel="telegram",
                role="user",
                content="Xin chào",
                external_message_id="501",
            )

        self.assertIsNone(result)

    def test_save_assistant_message_keeps_structured_metadata(self):
        connection = _Connection([_Cursor(one={"id": 18})])
        with patch(
            "app.database.conversation_repository.database_connection",
            return_value=_ConnectionContext(connection),
        ):
            result = ConversationRepository().save_message(
                conversation_id=17,
                channel="web",
                role="assistant",
                content="Dạ, mẫu S81Q8 hiện có màu Xanh Lá ạ.",
                intent="product_information",
                product_codes=["S81Q8"],
                total_ms=3054,
                delivery_status="generated",
            )

        self.assertEqual(result, 18)
        parameters = connection.calls[0][1]
        self.assertIn('"S81Q8"', parameters[8])
        self.assertEqual(parameters[15], 3054)

    def test_list_messages_caps_limit(self):
        rows = [{"id": 1, "role": "user", "content": "Hi"}]
        connection = _Connection([_Cursor(all_rows=rows)])
        with patch(
            "app.database.conversation_repository.database_connection",
            return_value=_ConnectionContext(connection),
        ):
            result = ConversationRepository().list_messages(
                channel="web",
                session_key="session-1",
                limit=5000,
            )

        self.assertEqual(result, rows)
        self.assertEqual(connection.calls[0][1][-1], 500)

    def test_invalid_role_is_rejected_before_database_call(self):
        with self.assertRaises(ValueError):
            ConversationRepository().save_message(
                conversation_id=1,
                channel="web",
                role="tool",
                content="invalid",
            )


if __name__ == "__main__":
    unittest.main()
