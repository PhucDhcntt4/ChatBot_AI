import unittest

from app.product_recognition.handler import ProductImageHandler


class ProductRecognitionArbitrationTests(unittest.TestCase):
    def test_weaker_top_recheck_does_not_replace_shortlist_winner(self):
        self.assertFalse(
            ProductImageHandler._should_override_shortlist(
                selected_confidence=1.0,
                top_exact=True,
                top_confidence=0.95,
            )
        )

    def test_near_certain_top_recheck_can_replace_weak_shortlist(self):
        self.assertTrue(
            ProductImageHandler._should_override_shortlist(
                selected_confidence=0.92,
                top_exact=True,
                top_confidence=0.99,
            )
        )

    def test_small_confidence_advantage_cannot_replace_shortlist(self):
        self.assertFalse(
            ProductImageHandler._should_override_shortlist(
                selected_confidence=0.96,
                top_exact=True,
                top_confidence=0.99,
            )
        )


if __name__ == "__main__":
    unittest.main()
