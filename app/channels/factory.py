from app.channels.base import ChannelProvider
from app.channels.providers import FacebookChannelProvider, TelegramChannelProvider
from app.config import (
    CHANNEL_PROVIDERS,
    FACEBOOK_GRAPH_API_VERSION,
    FACEBOOK_PAGE_ACCESS_TOKEN,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_SECRET,
)


def create_channel_providers() -> dict[str, ChannelProvider]:
    providers: dict[str, ChannelProvider] = {}
    if "telegram" in CHANNEL_PROVIDERS:
        if not TELEGRAM_BOT_TOKEN:
            raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN khi bật Telegram.")
        if not TELEGRAM_WEBHOOK_SECRET:
            raise RuntimeError("Thiếu TELEGRAM_WEBHOOK_SECRET khi bật Telegram.")
        telegram = TelegramChannelProvider(TELEGRAM_BOT_TOKEN)
        providers[telegram.channel_name] = telegram
    if "facebook" in CHANNEL_PROVIDERS:
        if not FACEBOOK_PAGE_ACCESS_TOKEN:
            raise RuntimeError(
                "Thiếu FACEBOOK_PAGE_ACCESS_TOKEN khi bật Facebook."
            )
        facebook = FacebookChannelProvider(
            FACEBOOK_PAGE_ACCESS_TOKEN,
            graph_api_version=FACEBOOK_GRAPH_API_VERSION,
        )
        providers[facebook.channel_name] = facebook
    return providers
