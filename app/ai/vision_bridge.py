from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.ai.base import AIProvider


@dataclass
class _VisionResponse:
    text: str


class ProviderVisionClient:
    """Compatibility bridge for recognition code using labeled content parts."""

    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider
        self.models = self

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: Any,
    ) -> _VisionResponse:
        del model
        response_model = getattr(config, "response_schema", None)
        if not response_model or not isinstance(response_model, type):
            raise RuntimeError("Vision request thiếu response_schema")

        text_parts: list[str] = []
        images: list[tuple[str, bytes, str]] = []
        pending_label = "IMAGE"
        values = contents if isinstance(contents, list) else [contents]
        for value in values:
            if isinstance(value, str):
                text_parts.append(value)
                pending_label = value
                continue
            inline_data = getattr(value, "inline_data", None)
            data = getattr(inline_data, "data", None)
            mime_type = getattr(inline_data, "mime_type", None)
            if data and mime_type:
                images.append((pending_label, bytes(data), str(mime_type)))

        system_instruction = getattr(config, "system_instruction", None)
        if system_instruction:
            text_parts.insert(0, str(system_instruction))
        parsed = self.provider.analyze_images(
            instruction="\n\n".join(text_parts),
            images=images,
            response_model=response_model,
        )
        if not isinstance(parsed, BaseModel):
            parsed = response_model.model_validate(parsed)
        return _VisionResponse(text=parsed.model_dump_json())
