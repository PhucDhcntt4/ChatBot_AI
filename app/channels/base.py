from typing import Any, Protocol

from app.channels.models import IncomingChannelMessage
from app.conversation.models import ConversationResponse


class ChannelProvider(Protocol):
    """Contract implemented by Telegram, Facebook and future transports."""

    channel_name: str

    def to_event(
        self, payload: dict[str, Any]
    ) -> tuple[IncomingChannelMessage | None, str | None]: ...

    def send_typing(self, recipient_id: str) -> None: ...

    def send_text(self, recipient_id: str, text: str) -> None: ...

    def send_media(self, recipient_id: str, urls: list[str]) -> None: ...

    def send_response(
        self, recipient_id: str, response: ConversationResponse
    ) -> None: ...
