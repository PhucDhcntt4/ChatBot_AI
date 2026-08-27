import logging
import re
import time
from pathlib import Path
from typing import Any

import requests

from app.channels.models import IncomingChannelMessage


logger = logging.getLogger("uvicorn.error")


class TelegramChannelProvider:
    channel_name = "telegram"

    def __init__(self, token: str) -> None:
        token = token.strip()
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
            raise RuntimeError("TELEGRAM_BOT_TOKEN không đúng định dạng.")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{token}"

    @staticmethod
    def extract(payload: dict[str, Any]) -> tuple[int | None, str, str | None]:
        message = payload.get("message")
        if not isinstance(message, dict):
            return None, "", None
        chat_id = (message.get("chat") or {}).get("id")
        if not isinstance(chat_id, int):
            return None, "", None
        text = str(message.get("text") or message.get("caption") or "").strip()
        photos = message.get("photo") or []
        largest = photos[-1] if isinstance(photos, list) and photos else {}
        file_id = (
            str(largest.get("file_id") or "").strip()
            if isinstance(largest, dict)
            else ""
        )
        return chat_id, text, file_id or None

    @staticmethod
    def _plain_text(text: str) -> str:
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", str(text), flags=re.DOTALL)
        text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)
        return re.sub(r"(?m)^\s*\*\s+", "• ", text).strip()

    def _post(self, method: str, payload: dict[str, Any], timeout: int = 30) -> Any:
        started = time.perf_counter()
        response = requests.post(
            f"{self.base_url}/{method}", json=payload, timeout=timeout
        )
        try:
            result = response.json()
        except ValueError as error:
            raise RuntimeError(f"Telegram {method} trả về dữ liệu không hợp lệ.") from error
        if not response.ok or not result.get("ok"):
            raise RuntimeError(
                f"Telegram {method} thất bại: "
                f"{result.get('description', response.status_code)}"
            )
        logger.info(
            "CHANNEL SENT provider=telegram method=%s time=%.3fs",
            method,
            time.perf_counter() - started,
        )
        return result.get("result")

    def send_typing(self, recipient_id: str) -> None:
        self._post(
            "sendChatAction",
            {"chat_id": recipient_id, "action": "typing"},
            timeout=15,
        )

    def send_text(self, recipient_id: str, text: str) -> None:
        self._post(
            "sendMessage",
            {"chat_id": recipient_id, "text": self._plain_text(text)},
        )

    def send_media(self, recipient_id: str, urls: list[str]) -> None:
        urls = list(dict.fromkeys(url for url in urls if url))[:10]
        if not urls:
            return
        if len(urls) == 1:
            self._post("sendPhoto", {"chat_id": recipient_id, "photo": urls[0]})
            return
        self._post(
            "sendMediaGroup",
            {
                "chat_id": recipient_id,
                "media": [{"type": "photo", "media": url} for url in urls],
            },
            timeout=60,
        )

    def download_image(self, file_id: str) -> tuple[bytes, str]:
        response = requests.get(
            f"{self.base_url}/getFile", params={"file_id": file_id}, timeout=20
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError("Telegram không trả về thông tin ảnh.")
        file_path = str(payload["result"]["file_path"])
        file_response = requests.get(
            f"{self.file_base_url}/{file_path}", timeout=30
        )
        file_response.raise_for_status()
        if len(file_response.content) > 20 * 1024 * 1024:
            raise ValueError("Ảnh Telegram vượt quá giới hạn 20 MB.")
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(Path(file_path).suffix.casefold(), "image/jpeg")
        return file_response.content, mime_type

    def to_event(
        self, payload: dict[str, Any]
    ) -> tuple[IncomingChannelMessage | None, str | None]:
        chat_id, text, file_id = self.extract(payload)
        if chat_id is None:
            return None, None
        image_bytes = None
        mime_type = None
        if file_id:
            image_bytes, mime_type = self.download_image(file_id)
        return IncomingChannelMessage(
            channel=self.channel_name,
            user_id=str(chat_id),
            text=text,
            image_bytes=image_bytes,
            mime_type=mime_type,
            external_message_id=(
                str((payload.get("message") or {}).get("message_id"))
                if (payload.get("message") or {}).get("message_id") is not None
                else None
            ),
            external_user_id=str(chat_id),
            media_metadata=(
                [{"telegram_file_id": file_id}]
                if file_id
                else None
            ),
        ), file_id

    def send_response(self, recipient_id: str, response) -> None:
        if response.content_blocks:
            for block in response.content_blocks:
                if block.type == "text" and block.text:
                    self.send_text(recipient_id, block.text)
                elif block.type == "media" and block.media:
                    try:
                        self.send_media(recipient_id, list(block.media.image_urls))
                    except Exception:
                        logger.exception(
                            "CHANNEL MEDIA ERROR provider=telegram recipient=%s code=%s",
                            recipient_id,
                            block.media.product_code,
                        )
            return

        self.send_text(recipient_id, response.message)
        for media in response.media:
            try:
                self.send_media(recipient_id, list(media.image_urls))
            except Exception:
                logger.exception(
                    "CHANNEL MEDIA ERROR provider=telegram recipient=%s code=%s",
                    recipient_id,
                    media.product_code,
                )
