import unittest

from app.conversation.content_blocks import build_content_blocks
from app.conversation.models import ProductMedia


class ContentBlocksTest(unittest.TestCase):
    def test_interleaves_each_product_with_its_album(self) -> None:
        products = [
            {"product_code": "G7737", "product_name": "Giày Búp Bê Dập Logo"},
            {"product_code": "G7736", "product_name": "Giày Búp Bê Quai Ngang"},
            {"product_code": "G5722", "product_name": "Giày Búp Bê Mary Jane"},
        ]
        media = [
            ProductMedia(product_code=code, image_urls=[f"https://cdn/{code}.jpg"])
            for code in ("G7737", "G7736", "G5722")
        ]
        message = """Dạ, em gửi anh/chị một số mẫu giày búp bê ạ.

Giày Búp Bê Dập Logo
- Mã: G7737

Giày Búp Bê Quai Ngang
- Mã: G7736

Giày Búp Bê Mary Jane
- Mã: G5722

Trong các mẫu trên, anh/chị muốn xem kỹ mẫu nào ạ?"""

        blocks = build_content_blocks(message, products, media)

        self.assertEqual(
            [block.type for block in blocks],
            ["text", "text", "media", "text", "media", "text", "media", "text"],
        )
        media_codes = [block.media.product_code for block in blocks if block.media]
        self.assertEqual(media_codes, ["G7737", "G7736", "G5722"])
        self.assertIn("G7737", blocks[1].text or "")
        self.assertIn("G7736", blocks[3].text or "")
        self.assertIn("G5722", blocks[5].text or "")
        self.assertTrue((blocks[-1].text or "").startswith("Trong các mẫu"))

    def test_keeps_legacy_order_when_sections_cannot_be_mapped(self) -> None:
        media = [
            ProductMedia(product_code="A1", image_urls=["https://cdn/A1.jpg"]),
            ProductMedia(product_code="A2", image_urls=["https://cdn/A2.jpg"]),
        ]
        blocks = build_content_blocks(
            "Nội dung không chứa tên hoặc mã sản phẩm.",
            [
                {"product_code": "A1", "product_name": "Sản phẩm A"},
                {"product_code": "A2", "product_name": "Sản phẩm B"},
            ],
            media,
        )
        self.assertEqual([block.type for block in blocks], ["text", "media", "media"])

    def test_places_single_product_cta_after_media(self) -> None:
        cta = "Anh/chị cần đặt hàng hay hỗ trợ thêm gì ạ?"
        blocks = build_content_blocks(
            f"Dạ, mẫu S81V3 hiện còn hàng ạ.\n\n{cta}",
            [{"product_code": "S81V3", "product_name": "Sandal S81V3"}],
            [
                ProductMedia(
                    product_code="S81V3",
                    image_urls=["https://cdn/S81V3.jpg"],
                )
            ],
            cta,
        )

        self.assertEqual(
            [block.type for block in blocks],
            ["text", "media", "text"],
        )
        self.assertEqual(blocks[-1].text, cta)

    def test_does_not_duplicate_cta_without_media(self) -> None:
        cta = "Anh/chị cần em hỗ trợ gì thêm ạ?"
        blocks = build_content_blocks(
            f"Dạ, em đã ghi nhận.\n\n{cta}",
            [],
            [],
            cta,
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].text or "").count(cta), 1)

    def test_product_section_starts_at_code_when_code_precedes_name(self) -> None:
        products = [
            {"product_code": "D32I7", "product_name": "Dép Xuồng 9CM"},
            {"product_code": "DHLN6", "product_name": "Dép Cao Gót 5CM"},
        ]
        media = [
            ProductMedia(
                product_code=code,
                image_urls=[f"https://cdn/{code}.jpg"],
            )
            for code in ("D32I7", "DHLN6")
        ]
        cta = "Anh/chị quan tâm mẫu nào ạ?"
        message = f"""Dạ, em nhận diện được 2 mẫu ạ.

- Mã: D32I7
- Tên: Dép Xuồng 9CM
- Giá: 850.000 đ

- Mã: DHLN6
- Tên: Dép Cao Gót 5CM
- Giá: 690.000 đ

{cta}"""

        blocks = build_content_blocks(message, products, media, cta)

        self.assertEqual(
            [block.type for block in blocks],
            ["text", "text", "media", "text", "media", "text"],
        )
        self.assertTrue((blocks[1].text or "").startswith("- Mã: D32I7"))
        self.assertNotIn("DHLN6", blocks[1].text or "")
        self.assertTrue((blocks[3].text or "").startswith("- Mã: DHLN6"))
        self.assertEqual(blocks[-1].text, cta)


if __name__ == "__main__":
    unittest.main()
