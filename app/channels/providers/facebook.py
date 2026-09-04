import logging
import re
import time
from typing import Any

import requests

from app.channels.models import IncomingChannelMessage, IncomingImage


logger = logging.getLogger("uvicorn.error")


class FacebookChannelProvider:
    """Facebook Messenger transport for the shared conversation core."""

    channel_name = "facebook"
    AI_MESSAGE_METADATA = "donghai_ai"

    def __init__(self, page_access_token: str, graph_api_version: str) -> None:
        self.page_access_token = page_access_token.strip()
        version = graph_api_version.strip().lstrip("/") or "v23.0"
        self.messages_url = (
            f"https://graph.facebook.com/{version}/me/messages"
        )

    @staticmethod
    def _plain_text(text: str) -> str:
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", str(text), flags=re.DOTALL)
        text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)
        return re.sub(r"(?m)^\s*\*\s+", "• ", text).strip()

    @staticmethod
    def extract(
        event: dict[str, Any],
    ) -> tuple[str | None, str, list[str], str | None]:
        sender_id = str((event.get("sender") or {}).get("id") or "").strip()
        message = event.get("message") or {}
        if not sender_id or not isinstance(message, dict) or message.get("is_echo"):
            return None, "", [], None
        text = str(message.get("text") or "").strip()
        image_urls: list[str] = []
        attachments = message.get("attachments") or []
        if isinstance(attachments, list):
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                if attachment.get("type") == "image":
                    image_url = str(
                        (attachment.get("payload") or {}).get("url") or ""
                    ).strip() or None
                    if image_url and image_url not in image_urls:
                        image_urls.append(image_url)
        mid = str(message.get("mid") or "").strip() or None
        return sender_id, text, image_urls[:5], mid

    def _post(self, payload: dict[str, Any], timeout: int = 30) -> Any:
        started = time.perf_counter()
        response = requests.post(
            self.messages_url,
            params={"access_token": self.page_access_token},
            json=payload,
            timeout=timeout,
        )
        try:
            result = response.json()
        except ValueError as error:
            raise RuntimeError(
                "Facebook Send API trả về dữ liệu không hợp lệ."
            ) from error
        if not response.ok or result.get("error"):
            detail = (result.get("error") or {}).get("message")
            raise RuntimeError(
                f"Facebook Send API thất bại: {detail or response.status_code}"
            )
        logger.debug(
            "CHANNEL SENT provider=facebook time=%.3fs",
            time.perf_counter() - started,
        )
        return result

    def send_typing(self, recipient_id: str) -> None:
        self._post(
            {"recipient": {"id": recipient_id}, "sender_action": "typing_on"},
            timeout=15,
        )

    def send_text(self, recipient_id: str, text: str) -> None:
        plain_text = self._plain_text(text)
        # Messenger text messages are limited; split on line boundaries.
        while plain_text:
            if len(plain_text) <= 1900:
                chunk, plain_text = plain_text, ""
            else:
                cut = plain_text.rfind("\n", 0, 1900)
                cut = cut if cut > 500 else 1900
                chunk, plain_text = plain_text[:cut], plain_text[cut:].lstrip()
            self._post(
                {
                    "recipient": {"id": recipient_id},
                    "messaging_type": "RESPONSE",
                    "message": {
                        "text": chunk,
                        "metadata": self.AI_MESSAGE_METADATA,
                    },
                }
            )

    def send_media(self, recipient_id: str, urls: list[str]) -> None:
        self.send_image_group(recipient_id, urls)

    def _send_single_image(self, recipient_id: str, url: str) -> None:
        self._post(
            {
                "recipient": {"id": recipient_id},
                "messaging_type": "RESPONSE",
                "message": {
                    "metadata": self.AI_MESSAGE_METADATA,
                    "attachment": {
                        "type": "image",
                        "payload": {
                            "url": url,
                            "is_reusable": True,
                        },
                    }
                },
            },
            timeout=60,
        )

    def send_image_group(
        self,
        recipient_id: str,
        urls: list[str],
    ) -> None:
        unique_urls = list(dict.fromkeys(url for url in urls if url))[:10]
        if not unique_urls:
            return

        if len(unique_urls) == 1:
            self._send_single_image(recipient_id, unique_urls[0])
            return

        attachments = [
            {
                "type": "image",
                "payload": {
                    "url": url,
                },
            }
            for url in unique_urls
        ]
        try:
            self._post(
                {
                    "recipient": {"id": recipient_id},
                    "messaging_type": "RESPONSE",
                    "message": {
                        "metadata": self.AI_MESSAGE_METADATA,
                        "attachments": attachments,
                    },
                },
                timeout=60,
            )
        except RuntimeError as error:
            logger.warning(
                "FACEBOOK IMAGE GROUP FAILED recipient=%s images=%s; "
                "fallback=single error=%s",
                recipient_id,
                len(unique_urls),
                error,
            )
            for url in unique_urls:
                try:
                    self._send_single_image(recipient_id, url)
                except Exception:
                    logger.exception(
                        "FACEBOOK IMAGE FAILED recipient=%s url=%s",
                        recipient_id,
                        url,
                    )

    @staticmethod
    def download_image(url: str) -> tuple[bytes, str]:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        if len(response.content) > 20 * 1024 * 1024:
            raise ValueError("Ảnh Facebook vượt quá giới hạn 20 MB.")
        mime_type = response.headers.get("content-type", "image/jpeg")
        mime_type = mime_type.split(";", 1)[0].strip().casefold()
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            mime_type = "image/jpeg"
        return response.content, mime_type

    def to_event(
        self, payload: dict[str, Any]
    ) -> tuple[IncomingChannelMessage | None, str | None]:
        sender_id, text, image_urls, mid = self.extract(payload)
        if sender_id is None:
            return None, None
        images: list[IncomingImage] = []
        media_metadata: list[dict[str, Any]] = []
        for image_url in image_urls:
            try:
                image_bytes, mime_type = self.download_image(image_url)
            except Exception:
                logger.exception(
                    "FACEBOOK DOWNLOAD IMAGE FAILED sender=%s url=%s",
                    sender_id,
                    image_url,
                )
                continue
            metadata = {"facebook_image_url": image_url}
            images.append(
                IncomingImage(
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    metadata=metadata,
                )
            )
            media_metadata.append(metadata)
        return IncomingChannelMessage(
            channel=self.channel_name,
            user_id=sender_id,
            text=text,
            images=images,
            external_message_id=mid,
            external_user_id=sender_id,
            media_metadata=media_metadata or None,
        ), mid

    def send_response(self, recipient_id: str, response) -> None:
        if response.content_blocks:
            for block in response.content_blocks:
                if block.type == "text" and block.text:
                    self.send_text(recipient_id, block.text)
                elif block.type == "media" and block.media:
                    self.send_image_group(
                        recipient_id,
                        list(block.media.image_urls),
                    )
            return
        self.send_text(recipient_id, response.message)
        for media in response.media:
            self.send_image_group(
                recipient_id,
                list(media.image_urls),
            )
