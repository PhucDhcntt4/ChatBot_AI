import re
from typing import Any

from app.conversation.models import ProductMedia, ResponseContentBlock


def build_content_blocks(
    message: str,
    products: list[dict[str, Any]],
    media: list[ProductMedia],
    cta_text: str | None = None,
) -> list[ResponseContentBlock]:
    """Build ordered text/media blocks for channel renderers."""
    message = message.strip()
    if not media:
        return [ResponseContentBlock(type="text", text=message)] if message else []

    message, detached_cta = _detach_cta(message, cta_text)

    media_by_code = {item.product_code.upper(): item for item in media}
    relevant = [product for product in products if _product_code(product) in media_by_code]
    if len(relevant) <= 1:
        return _append_cta(_plain_blocks(message, media), detached_cta)

    positions: list[tuple[int, dict[str, Any]]] = []
    for product in relevant:
        name = _product_name(product)
        code = _product_code(product)
        name_position = _line_start(message, name) if name else -1
        code_position = _line_start(message, code) if code else -1
        valid_positions = [
            item for item in (name_position, code_position) if item >= 0
        ]
        position = min(valid_positions) if valid_positions else -1
        if position < 0:
            return _append_cta(_plain_blocks(message, media), detached_cta)
        positions.append((position, product))

    positions.sort(key=lambda item: item[0])
    if len({position for position, _ in positions}) != len(positions):
        return _append_cta(_plain_blocks(message, media), detached_cta)

    blocks: list[ResponseContentBlock] = []
    intro = message[:positions[0][0]].strip()
    if intro:
        blocks.append(ResponseContentBlock(type="text", text=intro))

    trailing = ""
    for index, (start, product) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(message)
        section = message[start:end].strip()
        if index == len(positions) - 1:
            section, trailing = _split_trailing_text(section)
        if section:
            blocks.append(ResponseContentBlock(type="text", text=section))
        blocks.append(
            ResponseContentBlock(type="media", media=media_by_code[_product_code(product)])
        )

    if trailing:
        blocks.append(ResponseContentBlock(type="text", text=trailing))
    return _append_cta(blocks, detached_cta)


def _detach_cta(message: str, cta_text: str | None) -> tuple[str, str]:
    cta = (cta_text or "").strip()
    if not cta or not message.endswith(cta):
        return message, ""
    return message[: -len(cta)].rstrip(), cta


def _append_cta(
    blocks: list[ResponseContentBlock],
    cta: str,
) -> list[ResponseContentBlock]:
    if cta:
        blocks.append(ResponseContentBlock(type="text", text=cta))
    return blocks


def _product_code(product: dict[str, Any]) -> str:
    return str(product.get("product_code") or product.get("code") or "").strip().upper()


def _product_name(product: dict[str, Any]) -> str:
    return str(product.get("product_name") or product.get("name") or "").strip()


def _line_start(message: str, needle: str) -> int:
    match = re.search(rf"(?im)^.*{re.escape(needle)}.*$", message)
    return match.start() if match else -1


def _split_trailing_text(section: str) -> tuple[str, str]:
    paragraphs = re.split(r"\n\s*\n", section)
    trailing_markers = (
        "trong các mẫu", "trong cac mau",
        "anh/chị muốn", "anh/chi muon", "anh/chị cần", "anh/chi can",
        "anh/chị chọn", "anh/chi chon",
    )
    for index in range(1, len(paragraphs)):
        if paragraphs[index].strip().lower().startswith(trailing_markers):
            return (
                "\n\n".join(paragraphs[:index]).strip(),
                "\n\n".join(paragraphs[index:]).strip(),
            )
    return section, ""


def _plain_blocks(
    message: str,
    media: list[ProductMedia],
) -> list[ResponseContentBlock]:
    blocks = [ResponseContentBlock(type="text", text=message)] if message else []
    blocks.extend(ResponseContentBlock(type="media", media=item) for item in media)
    return blocks
