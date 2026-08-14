from decimal import Decimal
from typing import Any
import unicodedata

from app.database.connection import database_connection


class ProductRepository:
    @staticmethod
    def _number(value: Any) -> int | float | None:
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        return value

    @staticmethod
    def _normalize(value: Any) -> str:
        text = unicodedata.normalize("NFD", str(value or "").casefold())
        return "".join(
            character for character in text
            if unicodedata.category(character) != "Mn"
        ).replace("đ", "d")

    def health(self) -> dict[str, int]:
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT (SELECT COUNT(*) FROM products) AS products,
                       (SELECT COUNT(*) FROM product_variants) AS variants,
                       (SELECT COUNT(*) FROM product_images) AS images
                """
            ).fetchone()
        return dict(row or {})

    def product_types(self, active_only: bool = True) -> list[str]:
        status_clause = "AND status = 'ACTIVE'" if active_only else ""
        with database_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT product_type FROM products
                WHERE product_type IS NOT NULL AND product_type <> ''
                {status_clause}
                ORDER BY product_type
                """
            ).fetchall()
        return [str(row["product_type"]) for row in rows]

    def reference_products(
        self,
        product_type: str | None = None,
        limit: int = 5,
        images_per_product: int = 3,
    ) -> list[dict[str, Any]]:
        condition = "AND product_type = %s" if product_type else ""
        parameters: list[Any] = [product_type] if product_type else []
        parameters.append(limit)
        with database_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT product_code FROM products
                WHERE status = 'ACTIVE' {condition}
                ORDER BY id LIMIT %s
                """,
                parameters,
            ).fetchall()
        references = []
        for row in rows:
            product = self.public_info(str(row["product_code"]))
            if product and product["image_urls"]:
                references.append({
                    "product_code": product["product_code"],
                    "title": product["product_name"],
                    "product_type": product["product_type"],
                    "image_urls": product["image_urls"][:images_per_product],
                })
        return references

    def public_info(self, product_code: str) -> dict[str, Any] | None:
        code = product_code.strip().upper()
        if not code:
            return None
        with database_connection() as connection:
            product = connection.execute(
                "SELECT * FROM products WHERE product_code = %s", (code,)
            ).fetchone()
            if not product:
                return None
            variants = connection.execute(
                """
                SELECT color, size, price, inventory_quantity, available
                FROM product_variants WHERE product_id = %s
                ORDER BY color, size
                """,
                (product["id"],),
            ).fetchall()
            images = connection.execute(
                """
                SELECT color, source_url, local_path, is_featured
                FROM product_images
                WHERE product_id = %s AND is_active = TRUE
                ORDER BY image_order NULLS LAST, id
                """,
                (product["id"],),
            ).fetchall()

        colors: list[str] = []
        sizes: set[str] = set()
        prices: set[int | float] = set()
        availability: dict[str, dict[str, Any]] = {}
        for variant in variants:
            color = str(variant["color"] or "").strip()
            size = str(variant["size"] or "").strip()
            if color and color not in colors:
                colors.append(color)
            if variant["price"] is not None:
                prices.add(self._number(variant["price"]))
            if variant["available"] and size:
                sizes.add(size)
            if color:
                state = availability.setdefault(
                    color, {"available": False, "available_sizes": []}
                )
                if variant["available"]:
                    state["available"] = True
                    if size:
                        state["available_sizes"].append(size)

        image_urls: list[str] = []
        by_color: dict[str, list[str]] = {}
        for image in images:
            url = str(image["source_url"] or image["local_path"] or "").strip()
            if not url:
                continue
            if url not in image_urls:
                image_urls.append(url)
            color = str(image["color"] or "").strip()
            if color and url not in by_color.setdefault(color, []):
                by_color[color].append(url)

        return {
            "product_code": code,
            "product_name": product["title"],
            "product_type": product["product_type"],
            "description": product["description"] or "",
            "material": product["material"],
            "sole": product["sole"],
            "height": product["height"],
            "status": product["status"],
            "prices": sorted(prices),
            "colors": colors,
            "available_sizes": sorted(sizes),
            "availability_by_color": availability,
            "image_urls": image_urls,
            "image_urls_by_color": by_color,
        }

    def search(
        self, query: str, active_only: bool = True, limit: int = 5
    ) -> list[dict[str, Any]]:
        normalized = self._normalize(query).strip()
        if not normalized:
            return []
        tokens = {
            token for token in normalized.split()
            if token not in {"anh", "chi", "em", "shop", "co", "khong", "cho"}
        }
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT product_code, title, product_type, description, vendor, status
                FROM products ORDER BY id
                """
            ).fetchall()
        ranked: list[tuple[int, str]] = []
        for row in rows:
            if active_only and row["status"] != "ACTIVE":
                continue
            searchable = self._normalize(" ".join(str(row[key] or "") for key in row))
            matches = sum(token in searchable for token in tokens)
            if normalized in searchable:
                matches += 100
            if matches:
                ranked.append((matches, str(row["product_code"])))
        ranked.sort(key=lambda item: item[0], reverse=True)
        products = [self.public_info(code) for _, code in ranked[:limit]]
        return [product for product in products if product]

    def recommend_same_type(
        self,
        product_type: str,
        exclude_codes: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT product_code FROM products
                WHERE status = 'ACTIVE' AND product_type = %s
                  AND NOT (product_code = ANY(%s))
                ORDER BY random() LIMIT %s
                """,
                (product_type, exclude_codes or [""], limit),
            ).fetchall()
        products = [self.public_info(str(row["product_code"])) for row in rows]
        return [product for product in products if product]

    def recommend_by_query(self, query: str, limit: int) -> list[dict[str, Any]]:
        return self.search(query=query, limit=limit)
