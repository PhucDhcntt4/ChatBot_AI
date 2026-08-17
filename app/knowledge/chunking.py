import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    index: int
    heading: str | None
    content: str


HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def _blocks(text: str) -> list[tuple[str | None, str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[tuple[str | None, str]] = []
    heading: str | None = None
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            content = "\n".join(paragraph).strip()
            if content:
                blocks.append((heading, content))
            paragraph.clear()

    for line in text.splitlines():
        match = HEADING_PATTERN.match(line.strip())
        if match:
            flush()
            heading = match.group(1).strip()
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.rstrip())
    flush()
    return blocks


def _tail(text: str, length: int) -> str:
    if length <= 0:
        return ""
    if len(text) <= length:
        return text
    value = text[-length:]
    space = value.find(" ")
    return (value[space + 1 :] if space >= 0 else value).strip()


def chunk_text(
    text: str,
    max_chars: int = 1200,
    overlap_chars: int = 180,
) -> list[TextChunk]:
    if max_chars < 200:
        raise ValueError("RAG_CHUNK_SIZE phải từ 200 trở lên")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("RAG_CHUNK_OVERLAP phải nhỏ hơn RAG_CHUNK_SIZE")

    chunks: list[TextChunk] = []
    current_heading: str | None = None
    current = ""

    def emit() -> None:
        nonlocal current
        content = current.strip()
        if content:
            chunks.append(TextChunk(len(chunks), current_heading, content))
        current = _tail(content, overlap_chars)

    for heading, block in _blocks(text):
        if heading != current_heading and current.strip():
            emit()
            current = ""
        current_heading = heading
        remaining = block
        while remaining:
            separator = "\n\n" if current else ""
            available = max_chars - len(current) - len(separator)
            if available <= 0:
                emit()
                continue
            if len(remaining) <= available:
                current = f"{current}{separator}{remaining}".strip()
                remaining = ""
                continue
            split_at = remaining.rfind(" ", 0, available)
            if split_at < max(1, available // 2):
                split_at = available
            current = f"{current}{separator}{remaining[:split_at].strip()}".strip()
            remaining = remaining[split_at:].strip()
            emit()
    emit()
    return chunks
