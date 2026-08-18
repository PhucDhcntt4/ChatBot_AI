import re
import unicodedata
from pathlib import Path

from app.config import FAST_RESPONSE_PATH
from app.conversation.models import ConversationContext, SalesStage


class FastResponseService:
    """Return editable local replies for exact, low-risk social messages."""

    def __init__(self, path: str | Path = FAST_RESPONSE_PATH) -> None:
        self.path = Path(path)
        self._modified_at: int | None = None
        self._responses: dict[str, tuple[str, ...]] = {}

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize("NFD", value.casefold())
        value = "".join(
            character
            for character in value
            if unicodedata.category(character) != "Mn"
        ).replace("đ", "d")
        return re.sub(r"[^a-z0-9]+", " ", value).strip()

    def _load(self) -> None:
        if not self.path.is_file():
            self._responses = {}
            return
        modified_at = self.path.stat().st_mtime_ns
        if modified_at == self._modified_at:
            return

        responses: dict[str, list[str]] = {}
        triggers: list[str] = []
        replies: list[str] = []

        def commit() -> None:
            if not triggers or not replies:
                return
            values = tuple(reply.strip() for reply in replies if reply.strip())
            for trigger in triggers:
                normalized = self._normalize(trigger)
                if normalized:
                    responses[normalized] = list(values)

        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                commit()
                triggers, replies = [], []
            elif line.casefold().startswith("triggers:"):
                triggers.extend(
                    item.strip()
                    for item in line.split(":", 1)[1].split("|")
                    if item.strip()
                )
            elif line.casefold().startswith("reply:"):
                replies.append(line.split(":", 1)[1].strip())
        commit()
        self._responses = {
            trigger: tuple(values)
            for trigger, values in responses.items()
        }
        self._modified_at = modified_at

    def reply(
        self,
        message: str,
        context: ConversationContext,
    ) -> str | None:
        # Short acknowledgements during an order may mean confirm/change, so
        # they must continue through the AI order flow.
        if context.sales_stage != SalesStage.BROWSING:
            return None
        self._load()
        candidates = self._responses.get(self._normalize(message), ())
        if not candidates:
            return None
        assistant_turns = sum(
            1 for item in context.history if item.role == "assistant"
        )
        return candidates[assistant_turns % len(candidates)]
