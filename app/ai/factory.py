from app.ai.base import AIProvider
from app.config import AI_FALLBACK_PROVIDER, AI_PROVIDER


def _create_provider(provider_name: str) -> AIProvider:
    if provider_name == "gemini":
        from app.ai.providers.gemini import GeminiProvider

        return GeminiProvider()
    if provider_name == "openai":
        from app.ai.providers.openai import OpenAIProvider

        return OpenAIProvider()
    raise RuntimeError(
        "AI provider chỉ hỗ trợ 'gemini' hoặc 'openai': "
        f"{provider_name or '(trống)'}"
    )


def create_ai_provider() -> AIProvider:
    primary = _create_provider(AI_PROVIDER)
    if not AI_FALLBACK_PROVIDER:
        return primary
    if AI_FALLBACK_PROVIDER == AI_PROVIDER:
        raise RuntimeError("AI_FALLBACK_PROVIDER phải khác AI_PROVIDER")

    from app.ai.fallback import FallbackAIProvider

    return FallbackAIProvider(
        primary=primary,
        fallback=_create_provider(AI_FALLBACK_PROVIDER),
    )
