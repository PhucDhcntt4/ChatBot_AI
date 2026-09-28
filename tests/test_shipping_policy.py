import unittest
from unittest.mock import Mock, patch

from app.conversation.shipping_policy import ShippingPolicyService


class ShippingPolicyServiceTests(unittest.TestCase):
    def test_reads_active_category_documents_and_caches_content(self):
        client = Mock()
        client.details_by_category.return_value = [{
            "content": (
                "Goi tieu chuan\n"
                "Chuyen khoan truoc: mien ship\n"
                "Nhan hang thanh toan: 30.000 d\n"
                "Goi chuyen phat nhanh\n"
            ),
        }]
        context = Mock()
        context.__enter__ = Mock(return_value=client)
        context.__exit__ = Mock(return_value=False)

        with patch(
            "app.conversation.shipping_policy.admin_client",
            return_value=context,
        ):
            service = ShippingPolicyService()
            self.assertEqual(service.standard_fee("cod"), 30_000)
            self.assertEqual(service.standard_fee("bank_transfer"), 0)

        client.details_by_category.assert_called_once_with("shipping")


if __name__ == "__main__":
    unittest.main()
