import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from app.services import scheduled_inventory_sync as service


def variant(number=1, quantity=2, sku="SKU", size="39", status="ACTIVE"):
    return {
        "id": f"gid://shopify/ProductVariant/{number}",
        "sku": sku,
        "inventoryQuantity": quantity,
        "selectedOptions": [
            {"name": "Color", "value": "Đen"},
            {"name": "Size", "value": size},
        ],
        "product": {"status": status},
    }


def page(nodes, has_next=False, cursor=None):
    return {"productVariants": {
        "nodes": nodes,
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
    }}


class InventorySyncTests(unittest.TestCase):
    def test_shopify_filter_and_all_pages_with_duplicate_ids(self):
        with patch.object(service, "_fetch_inventory_page", side_effect=[
            page([variant()], True, "cursor1"),
            page([variant(), variant(2, 0)]),
        ]) as fetch:
            rows = list(service.iter_low_inventory_variants())
        self.assertEqual(len(rows), 2)
        self.assertEqual(fetch.call_args_list[0].args[0], {
            "first": 100, "after": None,
            "query": "inventory_quantity:<=2 AND product_status:ACTIVE",
        })
        self.assertEqual(fetch.call_args_list[1].args[0]["after"], "cursor1")
        self.assertNotIn("images", service.LOW_INVENTORY_QUERY)

    def test_missing_repeated_cursor_and_malformed_response_fail(self):
        cases = [
            [{}],
            [page([], True, None)],
            [page([], True, "same"), page([], True, "same")],
        ]
        for responses in cases:
            with self.subTest(responses=responses):
                with patch.object(service, "_fetch_inventory_page", side_effect=responses):
                    with self.assertRaises(RuntimeError):
                        list(service.iter_low_inventory_variants())

    def test_empty_shopify_result_never_opens_database(self):
        with patch.object(service, "_fetch_inventory_page", return_value=page([])):
            with patch.object(service, "database_connection") as database:
                result = service.sync_low_inventory()
        database.assert_not_called()
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["status"], "completed")

    def test_ineligible_results_never_open_database(self):
        rows = [variant(quantity=3), variant(quantity=None), variant(quantity=True),
                variant(sku=""), variant(status="DRAFT")]
        with patch.object(service, "iter_low_inventory_variants", return_value=iter(rows)):
            with patch.object(service, "database_connection") as database:
                result = service.sync_low_inventory()
        database.assert_not_called()
        self.assertEqual(result["skipped"], 5)

    def test_quantity_and_availability_mapping_is_variant_specific(self):
        rows = [variant(i, q, size=str(35 + i)) for i, q in enumerate([2, 1, 0, -1])]
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [{"id": 12}]
        connection.execute.return_value.rowcount = 1
        with patch.object(service, "iter_low_inventory_variants", return_value=iter(rows)):
            with patch.object(service, "database_connection") as database:
                database.return_value.__enter__.return_value = connection
                result = service.sync_low_inventory()
        calls = connection.execute.call_args_list
        self.assertEqual(result["updated"], 4)
        for index, quantity in enumerate([2, 1, 0, -1]):
            lookup, update = calls[index * 2:index * 2 + 2]
            self.assertEqual(lookup.args[1], (
                rows[index]["id"], "SKU", "den", str(35 + index),
            ))
            self.assertIn("p.status = 'ACTIVE'", lookup.args[0])
            self.assertEqual(update.args[1], (quantity, quantity > 0, 12, quantity, quantity > 0))
            self.assertIn("IS DISTINCT FROM", update.args[0])

    def test_unchanged_is_not_counted_as_update(self):
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [{"id": 12}]
        connection.execute.return_value.rowcount = 0
        with patch.object(service, "iter_low_inventory_variants", return_value=iter([variant()])):
            with patch.object(service, "database_connection") as database:
                database.return_value.__enter__.return_value = connection
                result = service.sync_low_inventory()
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["unchanged"], 1)

    def test_unmatched_or_ambiguous_rows_are_not_written(self):
        for matches in ([], [{"id": 1}, {"id": 2}]):
            with self.subTest(matches=matches):
                connection = Mock()
                connection.execute.return_value.fetchall.return_value = matches
                with patch.object(service, "iter_low_inventory_variants", return_value=iter([variant()])):
                    with patch.object(service, "database_connection") as database:
                        database.return_value.__enter__.return_value = connection
                        result = service.sync_low_inventory()
                self.assertEqual(connection.execute.call_count, 1)
                self.assertEqual(result["unmatched"], 1)
                self.assertEqual(result["updated"], 0)

    def test_commit_failure_is_not_counted_as_success(self):
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [{"id": 12}]
        connection.execute.return_value.rowcount = 1

        @contextmanager
        def database():
            yield connection
            raise RuntimeError("simulated commit failure")

        with patch.object(service, "iter_low_inventory_variants", return_value=iter([variant()])):
            with patch.object(service, "database_connection", database):
                with self.assertLogs(service.logger, level="ERROR"):
                    result = service.sync_low_inventory()
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["status"], "completed_with_errors")

    def test_shopify_error_propagates_without_database_access(self):
        with patch.object(service, "_fetch_inventory_page", side_effect=RuntimeError("API failed")):
            with patch.object(service, "database_connection") as database:
                with self.assertLogs(service.logger, level="INFO") as logs:
                    with self.assertRaisesRegex(RuntimeError, "API failed"):
                        service.sync_low_inventory()
        database.assert_not_called()
        self.assertTrue(any("status=interrupted" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
