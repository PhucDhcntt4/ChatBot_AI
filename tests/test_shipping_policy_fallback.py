import unittest

from fastapi import HTTPException

from app.conversation.models import ConversationContext
from app.conversation.order_flow import OrderFlowService


class UnavailableShippingPolicy:
    def standard_fee(self, payment_method):
        raise HTTPException(404, "shipping policy missing")


class ShippingPolicyFallbackTests(unittest.TestCase):
    def test_missing_remote_policy_does_not_break_order_summary(self):
        service = OrderFlowService(shipping_policy=UnavailableShippingPolicy())
        context = ConversationContext(session_id="shipping-fallback", channel="web")
        context.draft_payment_method = "cod"

        summary = service._summary(context, product=None)

        self.assertIsNone(summary["shipping_fee"])
        self.assertIsNone(summary["shipping_method"])
        self.assertIsNone(summary["total"])


if __name__ == "__main__":
    unittest.main()
