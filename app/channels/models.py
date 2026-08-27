from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IncomingImage:
    image_bytes: bytes
    mime_type: str
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class IncomingChannelMessage:
    channel: str
    user_id: str
    text: str = ""
    image_bytes: bytes | None = None
    mime_type: str | None = None
    images: list[IncomingImage] = field(default_factory=list)
    external_message_id: str | None = None
    external_user_id: str | None = None
    media_metadata: list[dict[str, Any]] | None = None

    @property
    def has_image(self) -> bool:
        return bool(self.images or (self.image_bytes and self.mime_type))
