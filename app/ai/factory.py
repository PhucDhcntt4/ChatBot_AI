from app.ai.base import AIProvider
from app.config import AI_PROVIDER


def create_ai_provider() -> AIProvider:
    if AI_PROVIDER == "gemini":
        from app.ai.providers.gemini import GeminiProvider
        return GeminiProvider()
    if AI_PROVIDER == "openai":
        from app.ai.providers.openai import OpenAIProvider
        return OpenAIProvider()
    raise RuntimeError("AI_PROVIDER chỉ hỗ trợ 'gemini' hoặc 'openai'")
