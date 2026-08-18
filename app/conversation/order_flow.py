import re
import unicodedata
from typing import Any

from app.conversation.models import (
    ConversationContext,
    ConversationPlan,
    ExecutionResult,
    SalesStage,
)
from app.conversation.shipping_policy import ShippingPolicyService


class OrderFlowService:
    def __init__(
        self,
        shipping_policy: ShippingPolicyService | None = None,
    ) -> None:
        self.shipping_policy = shipping_policy or ShippingPolicyService()

    @staticmethod
    def normalize_phone(value: str | None) -> str | None:
        digits = re.sub(r"\D", "", value or "")
        if digits.startswith("84"):
            digits = "0" + digits[2:]
        return digits if re.fullmatch(r"0\d{9}", digits) else None

    @staticmethod
    def _normalize(value: str | None) -> str:
        normalized = unicodedata.normalize("NFD", str(value or "").casefold())
        return "".join(
            character
            for character in normalized
            if unicodedata.category(character) != "Mn"
        ).replace("đ", "d").strip()

    @classmethod
    def normalize_payment(cls, value: str | None) -> str | None:
        normalized = cls._normalize(value)
        if normalized in {"cod", "tien mat", "thanh toan khi nhan hang"}:
            return "cod"
        if normalized in {"bank_transfer", "chuyen khoan", "bank"}:
            return "bank_transfer"
        return "other" if normalized == "other" else None

    @staticmethod
    def _clear(context: ConversationContext) -> None:
        context.draft_product_code = None
        context.draft_color = None
        context.draft_size = None
        context.draft_quantity = None
        context.draft_customer_name = None
        context.draft_customer_phone = None
        context.draft_shipping_address = None
        context.draft_payment_method = None
        context.draft_promotion_note = None
        context.draft_promotion_name = None
        context.draft_promotion_code = None
        context.draft_promotion_discount_amount = None
        context.draft_promotion_benefit = None
        context.draft_promotion_eligible = None
        context.cart_items = []
        context.confirmed_order_id = None
        context.sheet_export_status = None

    @staticmethod
    def _clear_current_item(context: ConversationContext) -> None:
        context.draft_product_code = None
        context.draft_color = None
        context.draft_size = None
        context.draft_quantity = None

    @staticmethod
    def _product_options(
        product: dict[str, Any] | None,
        field: str,
    ) -> list[str]:
        if not product:
            return []
        return list(dict.fromkeys(
            str(value).strip()
            for value in product.get(field, [])
            if str(value or "").strip()
        ))

    @classmethod
    def _apply_product_defaults(
        cls,
        context: ConversationContext,
        product: dict[str, Any] | None,
    ) -> None:
        colors = cls._product_options(product, "colors")
        sizes = cls._product_options(product, "available_sizes")
        if len(colors) == 1 and not context.draft_color:
            context.draft_color = colors[0]
        if len(sizes) == 1 and not context.draft_size:
            context.draft_size = sizes[0]

    @classmethod
    def missing_product_fields(
        cls,
        context: ConversationContext,
        product: dict[str, Any] | None = None,
    ) -> list[str]:
        values: dict[str, Any] = {
            "product_code": context.draft_product_code,
            "quantity": context.draft_quantity,
        }
        # Color and size are variant dimensions, not universal order fields.
        # Ask only when the catalog actually exposes that dimension.
        if cls._product_options(product, "colors"):
            values["color"] = context.draft_color
        if cls._product_options(product, "available_sizes"):
            values["size"] = context.draft_size
        return [name for name, value in values.items() if not value]

    @staticmethod
    def missing_contact_fields(context: ConversationContext) -> list[str]:
        values = {
            "customer_name": context.draft_customer_name,
            "customer_phone": context.draft_customer_phone,
            "shipping_address": context.draft_shipping_address,
            "payment_method": context.draft_payment_method,
        }
        return [name for name, value in values.items() if not value]

    @staticmethod
    def _matching_product(
        result: ExecutionResult,
        product_code: str | None,
    ) -> dict[str, Any] | None:
        return next(
            (
                product
                for product in result.products
                if product.get("product_code") == product_code
            ),
            result.products[0] if len(result.products) == 1 else None,
        )

    @classmethod
    def _product_errors(
        cls,
        context: ConversationContext,
        product: dict[str, Any] | None,
    ) -> list[str]:
        if not product:
            return ["product_not_found"]
        errors: list[str] = []
        color = context.draft_color or ""
        size = context.draft_size or ""
        colors = [str(item) for item in product.get("colors", [])]
        matched_color = next(
            (item for item in colors if cls._normalize(item) == cls._normalize(color)),
            None,
        )
        if color and not matched_color:
            errors.append("color_unavailable")
        if matched_color and size:
            available_sizes = [
                str(item)
                for item in (
                    product.get("availability_by_color", {})
                    .get(matched_color, {})
                    .get("available_sizes", [])
                )
            ]
            if available_sizes and size not in available_sizes:
                errors.append("size_unavailable_for_color")
        return errors

    def _selected_price(
        self,
        context: ConversationContext,
        product: dict[str, Any] | None,
    ) -> int | float | None:
        product = product or {}
        selected_price = next(
            (
                item.get("price")
                for item in product.get("variant_prices", [])
                if self._normalize(item.get("color"))
                == self._normalize(context.draft_color)
                and str(item.get("size") or "").strip()
                == str(context.draft_size or "").strip()
            ),
            None,
        )
        if selected_price is None:
            prices = product.get("prices") or []
            selected_price = prices[0] if len(prices) == 1 else None
        return selected_price

    def _current_item(
        self,
        context: ConversationContext,
        product: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        self._apply_product_defaults(context, product)
        if self.missing_product_fields(context, product):
            return None
        unit_price = self._selected_price(context, product)
        return {
            "product_name": (product or {}).get("product_name"),
            "product_code": context.draft_product_code,
            "color": context.draft_color,
            "size": context.draft_size,
            "quantity": context.draft_quantity,
            "unit_price": unit_price,
            "subtotal": (
                unit_price * context.draft_quantity
                if unit_price is not None and context.draft_quantity
                else None
            ),
        }

    def _upsert_current_item(
        self,
        context: ConversationContext,
        product: dict[str, Any] | None,
    ) -> None:
        item = self._current_item(context, product)
        if not item:
            return
        self._upsert_item(context, item)

    def _upsert_item(
        self,
        context: ConversationContext,
        item: dict[str, Any],
    ) -> None:
        identity = (
            item["product_code"],
            self._normalize(item["color"]),
            str(item["size"]),
        )
        for index, existing in enumerate(context.cart_items):
            existing_identity = (
                existing.get("product_code"),
                self._normalize(existing.get("color")),
                str(existing.get("size")),
            )
            if existing_identity == identity:
                context.cart_items[index] = item
                return
        context.cart_items.append(item)

    def _apply_requested_items(
        self,
        plan: ConversationPlan,
        context: ConversationContext,
        product: dict[str, Any] | None,
    ) -> list[str]:
        errors: list[str] = []
        for requested in plan.requested_items:
            code = requested.product_code or plan.reference_product_code
            if not product or product.get("product_code") != code:
                errors.append(f"product_not_found:{code}")
                continue
            item_context = context.model_copy(deep=True)
            item_context.draft_product_code = code
            item_context.draft_color = (
                requested.color.strip() if requested.color else None
            )
            item_context.draft_size = (
                requested.size.strip() if requested.size else None
            )
            item_context.draft_quantity = requested.quantity
            self._apply_product_defaults(item_context, product)
            if self.missing_product_fields(item_context, product):
                errors.append("item_fields_missing")
                continue
            item_errors = self._product_errors(item_context, product)
            if item_errors:
                errors.extend(f"{code}:{error}" for error in item_errors)
                continue
            item = self._current_item(item_context, product)
            if item:
                self._upsert_item(context, item)
                self._restore_current_from_item(context, item)
        return errors

    @staticmethod
    def _restore_current_from_item(
        context: ConversationContext,
        item: dict[str, Any] | None,
    ) -> None:
        if not item:
            OrderFlowService._clear_current_item(context)
            return
        context.draft_product_code = item.get("product_code")
        context.draft_color = item.get("color")
        context.draft_size = item.get("size")
        context.draft_quantity = item.get("quantity")

    @staticmethod
    def _compact_note(value: str | None, limit: int = 500) -> str | None:
        compacted = re.sub(r"\s+", " ", value or "").strip()
        if not compacted:
            return None
        if len(compacted) <= limit:
            return compacted
        return compacted[: limit - 3].rstrip() + "..."

    @staticmethod
    def _promotion_requested(plan: ConversationPlan) -> bool:
        return bool(
            "promotion" in {
            str(item).strip().casefold()
            for item in plan.requested_attributes
            }
            or plan.promotion_name
            or plan.promotion_code
            or plan.promotion_discount_amount is not None
            or plan.promotion_benefit
            or plan.promotion_eligible is not None
        )

    def _update_promotion_note(
        self,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> None:
        if not self._promotion_requested(plan):
            return
        if plan.promotion_name:
            context.draft_promotion_name = plan.promotion_name.strip()
        if plan.promotion_code:
            context.draft_promotion_code = plan.promotion_code.strip().upper()
        if plan.promotion_discount_amount is not None:
            context.draft_promotion_discount_amount = plan.promotion_discount_amount
        if plan.promotion_benefit:
            context.draft_promotion_benefit = plan.promotion_benefit.strip()
        if plan.promotion_eligible is not None:
            context.draft_promotion_eligible = plan.promotion_eligible

        details: list[str] = []
        if context.draft_promotion_name:
            details.append(f"Chương trình: {context.draft_promotion_name}")
        if context.draft_promotion_code:
            details.append(f"Mã: {context.draft_promotion_code}")
        if context.draft_promotion_discount_amount is not None:
            amount = f"{context.draft_promotion_discount_amount:,}".replace(",", ".")
            details.append(f"Giảm: {amount} đ")
        if context.draft_promotion_benefit:
            details.append(f"Quyền lợi: {context.draft_promotion_benefit}")
        if context.draft_promotion_eligible is True:
            details.append("Trạng thái: AI tạm tính đủ điều kiện; chờ nhân viên kiểm tra")
        elif context.draft_promotion_eligible is False:
            details.append("Trạng thái: Chưa đủ điều kiện áp dụng")

        if details:
            context.draft_promotion_note = " | ".join(details)
            return
        if result.knowledge_context:
            note = self._compact_note(result.knowledge_context)
            if note:
                context.draft_promotion_note = (
                    "Khách có hỏi/yêu cầu áp dụng khuyến mãi. "
                    f"Nội dung tham chiếu: {note}"
                )
                return
        context.draft_promotion_note = (
            "Khách có hỏi/yêu cầu áp dụng khuyến mãi hoặc mã giảm giá. "
            "Nhân viên cần kiểm tra chương trình áp dụng trước khi tạo đơn chính thức."
        )

    def _summary(
        self,
        context: ConversationContext,
        product: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_item = self._current_item(context, product)
        items = [dict(item) for item in context.cart_items]
        if current_item and not any(
            item.get("product_code") == current_item.get("product_code")
            and self._normalize(item.get("color"))
            == self._normalize(current_item.get("color"))
            and str(item.get("size")) == str(current_item.get("size"))
            for item in items
        ):
            items.append(current_item)
        subtotals = [item.get("subtotal") for item in items]
        subtotal = (
            sum(subtotals)
            if items and all(value is not None for value in subtotals)
            else None
        )
        shipping_fee = self.shipping_policy.standard_fee(
            context.draft_payment_method
        )
        discount_amount = (
            (context.draft_promotion_discount_amount or 0)
            if context.draft_promotion_eligible is True
            else 0
        )
        discounted_subtotal = (
            max(subtotal - discount_amount, 0)
            if subtotal is not None
            else None
        )
        total = (
            discounted_subtotal + shipping_fee
            if discounted_subtotal is not None and shipping_fee is not None
            else None
        )
        return {
            "items": items,
            "item_count": len(items),
            "product_name": (current_item or {}).get("product_name"),
            "product_code": context.draft_product_code,
            "color": context.draft_color,
            "size": context.draft_size,
            "quantity": context.draft_quantity,
            "unit_price": (current_item or {}).get("unit_price"),
            "subtotal": subtotal,
            "promotion_discount_amount": discount_amount,
            "discounted_subtotal": discounted_subtotal,
            "shipping_method": "standard" if shipping_fee is not None else None,
            "shipping_fee": shipping_fee,
            "total": total,
            "customer_name": context.draft_customer_name,
            "customer_phone": context.draft_customer_phone,
            "shipping_address": context.draft_shipping_address,
            "payment_method": context.draft_payment_method,
            "promotion_note": context.draft_promotion_note,
        }

    def apply(
        self,
        plan: ConversationPlan,
        result: ExecutionResult,
        context: ConversationContext,
    ) -> None:
        if plan.order_action == "cancel":
            self._clear(context)
            context.sales_stage = SalesStage.CANCELLED
            result.success = True
            result.status = "order_cancelled"
            result.facts["order_cancelled"] = True
            return

        product = self._matching_product(result, plan.reference_product_code)
        if plan.order_action == "remove_item":
            remove_code = (
                plan.reference_product_code
                or context.draft_product_code
                or context.latest_product_code
            )
            before = len(context.cart_items)
            context.cart_items = [
                item
                for item in context.cart_items
                if item.get("product_code") != remove_code
            ]
            removed = len(context.cart_items) < before
            if context.draft_product_code == remove_code:
                self._restore_current_from_item(
                    context,
                    context.cart_items[-1] if context.cart_items else None,
                )
            missing_product = (
                [] if context.cart_items else self.missing_product_fields(context, product)
            )
            missing_contact = self.missing_contact_fields(context)
            if not context.cart_items:
                context.sales_stage = SalesStage.COLLECTING_PRODUCT
            elif missing_contact:
                context.sales_stage = SalesStage.COLLECTING_CONTACT
            else:
                context.sales_stage = SalesStage.AWAITING_FINAL_CONFIRMATION
            result.success = removed
            result.status = "order_item_removed" if removed else "order_item_not_found"
            result.facts.update({
                "removed_product_code": remove_code if removed else None,
                "order_draft": self._summary(context, None),
                "missing_product_fields": missing_product,
                "missing_contact_fields": missing_contact,
                "sales_stage": context.sales_stage.value,
            })
            return

        if plan.order_action == "confirm":
            self._update_promotion_note(plan, result, context)
            if (
                context.sales_stage == SalesStage.AWAITING_FINAL_CONFIRMATION
                and bool(context.cart_items)
                and not self.missing_contact_fields(context)
            ):
                context.sales_stage = SalesStage.CONFIRMED
                result.success = True
                result.status = "order_confirmed"
                result.facts["order_confirmed"] = True
                result.facts["order_summary"] = self._summary(context, product)
            else:
                result.facts["confirmation_rejected"] = True
            return

        has_order_data = any((
            plan.requested_color,
            plan.requested_size,
            plan.requested_quantity,
            plan.customer_name,
            plan.customer_phone,
            plan.shipping_address,
            plan.payment_method,
            plan.requested_items,
            "promotion" in {
                str(item).strip().casefold()
                for item in plan.requested_attributes
            },
        ))
        active = context.sales_stage in {
            SalesStage.COLLECTING_PRODUCT,
            SalesStage.COLLECTING_CONTACT,
            SalesStage.AWAITING_FINAL_CONFIRMATION,
        }
        if not (
            plan.buying_intent
            or plan.order_action in {"change", "add_item"}
            or (active and has_order_data)
        ):
            return

        product_code = (
            (product or {}).get("product_code")
            or plan.reference_product_code
            or context.draft_product_code
            or context.latest_product_code
        )
        previous_item_identity = None
        if (
            plan.order_action == "change"
            and context.draft_product_code
            and any((
                plan.requested_color,
                plan.requested_size,
                plan.requested_quantity,
            ))
        ):
            previous_item_identity = (
                context.draft_product_code,
                self._normalize(context.draft_color),
                str(context.draft_size or ""),
            )
        if (
            plan.buying_intent
            and context.sales_stage in {
                SalesStage.BROWSING,
                SalesStage.CONFIRMED,
                SalesStage.CANCELLED,
            }
        ):
            self._clear(context)
        if product_code and context.draft_product_code != product_code:
            # A completed previous selection was already persisted when its
            # last required field was collected, so only reset the editor for
            # the newly selected product here.
            context.draft_product_code = product_code
            context.draft_color = None
            context.draft_size = None
            context.draft_quantity = None
        if plan.requested_color:
            context.draft_color = plan.requested_color.strip()
        if plan.requested_size:
            context.draft_size = plan.requested_size.strip()
        if plan.requested_quantity:
            context.draft_quantity = plan.requested_quantity
        if plan.customer_name:
            context.draft_customer_name = plan.customer_name.strip()
        if plan.customer_phone:
            phone = self.normalize_phone(plan.customer_phone)
            if phone:
                context.draft_customer_phone = phone
            else:
                result.facts["invalid_phone"] = True
        if plan.shipping_address:
            address = plan.shipping_address.strip()
            if len(address) >= 8:
                context.draft_shipping_address = address
            else:
                result.facts["invalid_address"] = True
        if plan.payment_method:
            context.draft_payment_method = self.normalize_payment(plan.payment_method)
        self._update_promotion_note(plan, result, context)

        self._apply_product_defaults(context, product)

        requested_item_errors = self._apply_requested_items(
            plan,
            context,
            product,
        )

        missing_product = self.missing_product_fields(context, product)
        product_errors = (
            requested_item_errors
            or (self._product_errors(context, product) if not missing_product else [])
        )
        if not missing_product and not product_errors:
            if previous_item_identity:
                context.cart_items = [
                    item
                    for item in context.cart_items
                    if (
                        item.get("product_code"),
                        self._normalize(item.get("color")),
                        str(item.get("size") or ""),
                    ) != previous_item_identity
                ]
            self._upsert_current_item(context, product)
        missing_contact = self.missing_contact_fields(context)
        if missing_product or product_errors:
            context.sales_stage = SalesStage.COLLECTING_PRODUCT
        elif missing_contact:
            context.sales_stage = SalesStage.COLLECTING_CONTACT
        else:
            context.sales_stage = SalesStage.AWAITING_FINAL_CONFIRMATION

        result.success = True
        result.status = "order_flow_updated"
        result.facts.update({
            "order_draft": self._summary(context, product),
            "missing_product_fields": missing_product,
            "product_validation_errors": product_errors,
            "missing_contact_fields": missing_contact,
            "sales_stage": context.sales_stage.value,
        })
