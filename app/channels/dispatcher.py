import logging

from app.channels.models import IncomingChannelMessage
from app.conversation.models import ConversationResponse
from app.services.conversation_history_service import ConversationHistoryService
from app.services.human_mode_service import HumanModeService


logger = logging.getLogger("uvicorn.error")


class ChannelDispatcher:
    """Route normalized channel messages into the shared V2 business core."""

    def __init__(
        self,
        conversation_service,
        image_conversation_service,
        history_service: ConversationHistoryService | None = None,
        human_mode_service: HumanModeService | None = None,
    ) -> None:
        self.conversation = conversation_service
        self.image_conversation = image_conversation_service
        self.history = history_service
        self.human_mode = human_mode_service

    def dispatch(self, event: IncomingChannelMessage) -> ConversationResponse:
        response, _ = self.dispatch_with_history(event)
        return response

    def dispatch_with_history(
        self,
        event: IncomingChannelMessage,
        *,
        respect_human_mode: bool = False,
    ) -> tuple[ConversationResponse | None, int | None]:
        if self.history is not None:
            self.history.save_user_message(
                session_id=event.user_id,
                channel=event.channel,
                content=event.text,
                external_message_id=event.external_message_id,
                external_user_id=event.external_user_id or event.user_id,
                message_type="image" if event.has_image else "text",
                media=event.media_metadata,
                metadata={"mime_type": event.mime_type} if event.mime_type else None,
            )

        if (
            respect_human_mode
            and self.human_mode is not None
            and self.human_mode.is_enabled(event.channel, event.user_id)
        ):
            logger.info(
                "CHANNEL HUMAN MODE channel=%s session=%s action=skip_ai",
                event.channel,
                event.user_id,
            )
            return None, None

        if event.has_image:
            if event.images:
                response = self.image_conversation.recognize_many(
                    images=event.images,
                    caption=event.text,
                    session_id=event.user_id,
                    channel=event.channel,
                )
            else:
                response = self.image_conversation.recognize(
                    image_bytes=event.image_bytes,
                    mime_type=event.mime_type,
                    caption=event.text,
                    session_id=event.user_id,
                    channel=event.channel,
                )
        elif not event.text.strip():
            raise ValueError("Tin nhắn không có nội dung.")
        else:
            response = self.conversation.chat(
                message=event.text.strip(),
                session_id=event.user_id,
                channel=event.channel,
            )

        assistant_message_id = None
        if self.history is not None:
            assistant_message_id = self.history.save_assistant_message(
                session_id=event.user_id,
                channel=event.channel,
                response=response,
            )
        if (
            respect_human_mode
            and self.human_mode is not None
            and response.status == "human_handoff_requested"
        ):
            self.human_mode.enable(
                event.channel,
                event.user_id,
                reason="customer_requested",
                activated_by="bot",
            )
        return response, assistant_message_id

    def reset(self, channel: str, user_id: str) -> None:
        self.conversation.context_store.reset(user_id, channel)
        if self.human_mode is not None:
            self.human_mode.disable(channel, user_id)
