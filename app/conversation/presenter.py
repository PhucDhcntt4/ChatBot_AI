import re
import unicodedata

from app.ai.base import AIProvider
from app.conversation.models import (
    CTAType,
    ConversationContext,
    ConversationIntent,
    ConversationPlan,
    ExecutionResult,
)


class ConversationPresenter:
    INSUFFICIENT_KNOWLEDGE_REPLY = (
        "Dạ, hiện tại em chưa có đủ thông tin để có thể hỗ trợ "
        "anh/chị về nội dung này ạ."
    )

    def __init__(self, ai: AIProvider) -> None:
        self.ai = ai

    def present(
        self,
        message: str,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> str:
        if self._has_insufficient_knowledge(plan, result):
            return self.INSUFFICIENT_KNOWLEDGE_REPLY
        reply = self.naturalize_acknowledgement(
            self.normalize_customer_address(
                self.ai.present(message, plan, result, context).strip()
            )
        )
        reply = self.remove_embedded_media_urls(reply, result)
        reply = self.enforce_product_reply_format(reply, plan)
        reply = self.enforce_order_summary_format(reply, result)
        reply = self.ensure_media_lead(reply, result)
        if reply:
            return self.with_cta(reply, result)
        # A partial contact reply does not need an acknowledgement bubble.
        # When the mechanical acknowledgement was removed, return the one
        # backend-selected question directly instead of generating a fallback.
        if result.cta_text:
            return result.cta_text.strip()
        fallback = (
            "Dạ, hiện tại em chưa có đủ thông tin để hỗ trợ chính xác. "
            "Anh/chị cho em thêm mã sản phẩm hoặc nhu cầu cụ thể nhé."
        )
        return self.with_cta(fallback, result)

    @staticmethod
    def _has_insufficient_knowledge(
        plan: ConversationPlan,
        result: ExecutionResult,
    ) -> bool:
        if plan.intent == ConversationIntent.UNKNOWN:
            return True
        if plan.intent == ConversationIntent.POLICY_QUESTION:
            return not result.knowledge_context
        return result.status in {
            "knowledge_not_found",
            "knowledge_service_disabled",
            "intent_unknown",
        }

    @staticmethod
    def normalize_customer_address(text: str) -> str:
        def replacement(match: re.Match[str]) -> str:
            return "Anh/chị" if match.group(0)[0].isupper() else "anh/chị"

        return re.sub(
            r"\b(?:bạn|quý\s+khách)\b",
            replacement,
            text,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def naturalize_acknowledgement(text: str) -> str:
        """Remove mechanical order acknowledgements occasionally emitted by AI."""

        text = re.sub(
            r"\bDạ,?\s*em\s+(?:đã\s+)?ghi nhận\s+mẫu\s+(.+?)"
            r"\s+vào\s+đơn\s+cho\s+(?:anh/chị|anh|chị)\s+ạ\.?",
            r"Dạ, anh/chị đang chọn mẫu \1 ạ.",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bDạ,?\s*em\s+(?:đã\s+)?ghi nhận\s+thông tin\s+của\s+"
            r"(?:anh/chị|anh|chị)?[^.!?\n]*[.!?]?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"^\s*Dạ,?\s*em\s+cảm\s+ơn\s+anh/chị\s+ạ[.!]?\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    @staticmethod
    def remove_embedded_media_urls(
        text: str,
        result: ExecutionResult,
    ) -> str:
        """Remove product image URLs that channel renderers send as media."""

        media_urls = {
            url.strip()
            for media in result.media
            for url in media.image_urls
            if url.strip()
        }
        if not media_urls:
            return text.strip()

        kept_lines: list[str] = []
        for line in text.splitlines():
            comparable = line.replace(r"\_", "_").strip()
            if any(url in comparable for url in media_urls):
                continue
            kept_lines.append(line.rstrip())

        cleaned = "\n".join(kept_lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def enforce_product_reply_format(
        text: str,
        plan: ConversationPlan,
    ) -> str:
        """Keep catalog replies concise even when the model adds extra fields."""

        blocked_labels = {"mo ta"}
        if plan.intent == ConversationIntent.PRODUCT_RECOMMENDATION:
            blocked_labels.update({"chat lieu", "de", "chieu cao", "cao"})

        kept_lines: list[str] = []
        for line in text.splitlines():
            match = re.match(r"^\s*[-•]\s*([^:]+)\s*:", line)
            if match:
                label = match.group(1).casefold()
                label = re.sub(r"\s+", " ", label).strip()
                normalized = "".join(
                    character
                    for character in unicodedata.normalize("NFD", label)
                    if unicodedata.category(character) != "Mn"
                ).replace("đ", "d")
                if normalized in blocked_labels:
                    continue
            kept_lines.append(line.rstrip())
        return re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()

    @staticmethod
    def enforce_order_summary_format(
        text: str,
        result: ExecutionResult,
    ) -> str:
        """Hide promotion-only totals when no promotion is applied."""

        order = result.facts.get("order_draft")
        if not isinstance(order, dict):
            return text.strip()
        promotion_applied = bool(order.get("promotion_note")) and (
            order.get("discounted_subtotal") is not None
        )
        if promotion_applied:
            discount_amount = int(
                order.get("promotion_discount_amount") or 0
            )
            formatted_discount = (
                f"{discount_amount:,}".replace(",", ".") + "đ"
            )
            cleaned = re.sub(
                r"(?im)^\s*[-•]\s*khuyến\s+mãi\s*:.*$",
                f"- Khuyến mãi: {formatted_discount}",
                text,
            )
            return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        cleaned = re.sub(
            r"(?im)^\s*[-•]\s*tiền\s+sản\s+phẩm\s+sau\s+ưu\s+đãi\s*:.*(?:\n|$)",
            "",
            text,
        )
        cleaned = re.sub(
            r"(?im)^\s*[-•]\s*khuyến\s+mãi\s*:.*(?:\n|$)",
            "",
            cleaned,
        )
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    @staticmethod
    def ensure_media_lead(
        text: str,
        result: ExecutionResult,
    ) -> str:
        """Ensure customers are told that the following block contains images."""

        if not result.media:
            return text.strip()
        text = ConversationPresenter.remove_generated_cta_before_media(
            text,
            result,
        )
        if re.search(
            r"(?:gửi|mời)[^\n.!?]{0,80}(?:xem|hình|ảnh)",
            text,
            flags=re.IGNORECASE,
        ):
            return text.strip()
        lead = "Em gửi anh/chị xem hình thực tế mẫu này nhé 👇"
        return f"{text.strip()}\n\n{lead}" if text.strip() else lead

    @staticmethod
    def remove_generated_cta_before_media(
        text: str,
        result: ExecutionResult,
    ) -> str:
        """Drop an AI-invented CTA so the backend CTA can follow the album."""

        cta = (result.cta_text or "").strip()
        if not cta:
            return text.strip()
        paragraphs = re.split(r"\n\s*\n", text.strip())
        if not paragraphs:
            return text.strip()

        # The model sometimes places the verified CTA immediately before the
        # media lead. Remove that exact paragraph here; with_cta() will append
        # it again and content_blocks will move it behind the album.
        comparable_cta = re.sub(r"\s+", " ", cta).casefold()
        paragraphs = [
            paragraph
            for paragraph in paragraphs
            if re.sub(r"\s+", " ", paragraph.strip()).casefold()
            != comparable_cta
        ]
        if not paragraphs:
            return ""

        # If the media lead is already the final paragraph, inspect the
        # paragraph immediately before it for an AI-invented CTA as well.
        candidate_index = len(paragraphs) - 1
        if re.search(
            r"(?:gửi|mời)[^\n.!?]{0,80}(?:xem|hình|ảnh)",
            paragraphs[candidate_index],
            flags=re.IGNORECASE,
        ):
            candidate_index -= 1
        if candidate_index < 0:
            return "\n\n".join(paragraphs).strip()

        candidate = paragraphs[candidate_index].strip()
        looks_like_cta = bool(
            re.match(
                r"^(?:dạ[, ]+)?(?:nếu\s+)?anh/chị\b",
                candidate,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"(?:muốn|cần|chọn|ưng|quan tâm|tư vấn|hỗ trợ|đặt|mua|chốt)",
                candidate,
                flags=re.IGNORECASE,
            )
        )
        if looks_like_cta:
            paragraphs.pop(candidate_index)
        return "\n\n".join(paragraphs).strip()

    @staticmethod
    def with_cta(reply: str, result: ExecutionResult) -> str:
        cta = (result.cta_text or "").strip()
        normalized_reply = reply.strip()
        if cta:
            initial_reply = re.sub(r"\s+", " ", normalized_reply).casefold()
            initial_cta = re.sub(r"\s+", " ", cta).casefold()
            reply_without_greeting = re.sub(
                r"^dạ[, ]+",
                "",
                initial_reply,
                flags=re.IGNORECASE,
            )
            if reply_without_greeting == initial_cta:
                return normalized_reply
            # The presenter model is instructed not to invent a CTA, but an
            # occasional response still appends a request such as "Anh/chị
            # cho em xin...".  Remove that trailing generated request and let
            # the deterministic CTA selected from the order state be the only
            # call to action shown to the customer.
            while normalized_reply:
                previous_reply = normalized_reply
                normalized_reply = re.sub(
                    r"(?:\n+|\s{2,}|(?<=[.!?])\s+)"
                    r"(?:anh/chị\s+cho\s+em|em\s+xin|mẫu\s+này\s+anh/chị)"
                    r"[^\n]*$",
                    "",
                    normalized_reply,
                    flags=re.IGNORECASE,
                ).rstrip()
                paragraphs = re.split(r"\n\s*\n", normalized_reply)
                trailing = re.sub(r"\s+", " ", paragraphs[-1]).strip()
                generated_cta = bool(
                    trailing.endswith("?")
                    or (
                        re.match(
                            r"^(?:dạ[, ]*)?(?:anh/chị|em\s+xin|mẫu\s+này|"
                            r"trong\s+(?:các|những)|nếu\s+anh/chị)\b",
                            trailing,
                            flags=re.IGNORECASE,
                        )
                        and re.search(
                            r"(?:cho\s+em|gửi\s+em|xin|muốn|cần|chọn|ưng|"
                            r"quan\s+tâm|xem|kiểm\s+tra|xác\s+nhận|vui\s+lòng)",
                            trailing,
                            flags=re.IGNORECASE,
                        )
                    )
                )
                if generated_cta:
                    paragraphs.pop()
                    normalized_reply = "\n\n".join(paragraphs).strip()
                if normalized_reply == previous_reply:
                    break
        comparable_reply = re.sub(r"\s+", " ", normalized_reply).casefold()
        comparable_cta = re.sub(r"\s+", " ", cta).casefold()
        if (
            result.cta_type == CTAType.PROVIDE_MORE_INFO
            and re.search(
                r"(?:gửi|cho|cung cấp)[^.\n]{0,100}"
                r"(?:mã sản phẩm|ảnh rõ hơn|mô tả rõ hơn|thông tin)",
                normalized_reply,
                flags=re.IGNORECASE,
            )
        ):
            return normalized_reply
        if not cta or comparable_cta in comparable_reply:
            return normalized_reply
        return f"{normalized_reply}\n\n{cta}" if normalized_reply else cta
