from decimal import Decimal
import re
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

    @classmethod
    def match_product_type(
        cls,
        query: str,
        product_types: list[str],
    ) -> str | None:
        """Resolve an explicit catalog type without maintaining hardcoded aliases."""
        normalized_query = cls._normalize(query)
        query_tokens = set(normalized_query.split())
        matches: list[tuple[int, int, str]] = []
        for product_type in product_types:
            # The code in parentheses (for example MGT) is catalog metadata,
            # not part of the natural-language category name.
            type_name = re.sub(r"\([^)]*\)", " ", product_type)
            normalized_type = " ".join(cls._normalize(type_name).split())
            if not normalized_type:
                continue
            type_tokens = set(normalized_type.split())
            if normalized_type in normalized_query:
                matches.append((2, len(type_tokens), product_type))
                continue
            # A full token match supports reordered category words while the
            # minimum of two tokens prevents broad types such as "NAM".
            if len(type_tokens) >= 2 and type_tokens.issubset(query_tokens):
                matches.append((1, len(type_tokens), product_type))
        if not matches:
            return None
        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return matches[0][2]

    def resolve_product_type(self, query: str) -> str | None:
        return self.match_product_type(query, self.product_types())

    @classmethod
    def should_enforce_product_type(cls, product_type: str | None) -> bool:
        """Only hard-filter sufficiently specific catalog taxonomies.

        A broad one-word type such as ``SANDAL (MSD)`` must not exclude more
        specific types such as sandal nữ đế bằng/cao gót before title ranking.
        """
        if not product_type:
            return False
        type_name = re.sub(r"\([^)]*\)", " ", product_type)
        return len(cls._normalize(type_name).split()) >= 2

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
        variant_prices: list[dict[str, Any]] = []
        availability: dict[str, dict[str, Any]] = {}
        for variant in variants:
            color = str(variant["color"] or "").strip()
            size = str(variant["size"] or "").strip()
            if color and color not in colors:
                colors.append(color)
            if variant["price"] is not None:
                normalized_price = self._number(variant["price"])
                prices.add(normalized_price)
                variant_prices.append({
                    "color": color,
                    "size": size,
                    "price": normalized_price,
                    "available": bool(variant["available"]),
                })
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
            # Customer-facing media and Gemini verification use the public
            # Shopify CDN URL. local_path remains available for embeddings.
            url = str(image["source_url"] or "").strip()
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
            "variant_prices": variant_prices,
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
        resolved_type = self.resolve_product_type(query)
        raw_query = str(query).casefold().strip()
        preserve_accents = raw_query != normalized
        def word_tokens(value: Any) -> set[str]:
            text = str(value or "").casefold()
            if not preserve_accents:
                text = self._normalize(text)
            return set(re.findall(r"\w+", text, flags=re.UNICODE))

        stopwords = {
            "anh", "chị", "chi", "em", "shop", "có", "co", "không",
            "khong", "cho", "mẫu", "mau", "thôi", "thoi", "ạ", "a",
        }
        tokens = {
            token for token in word_tokens(query)
            if token not in stopwords
        }
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT product_code, title, product_type, description, vendor, status
                FROM products ORDER BY id
                """
            ).fetchall()
        exact_codes = [
            str(row["product_code"])
            for row in rows
            if (not active_only or row["status"] == "ACTIVE")
            and normalized
            == self._normalize(str(row["title"] or "")).strip()
        ]
        if exact_codes:
            products = [
                self.public_info(code)
                for code in exact_codes[:limit]
            ]
            return [product for product in products if product]

        enforce_type = self.should_enforce_product_type(resolved_type)
        ranked: list[tuple[int, str]] = []
        for row in rows:
            if active_only and row["status"] != "ACTIVE":
                continue
            if enforce_type and row["product_type"] != resolved_type:
                continue
            title = str(row["title"] or "")
            product_type = str(row["product_type"] or "")
            title_tokens = word_tokens(title)
            type_tokens = word_tokens(re.sub(r"\([^)]*\)", " ", product_type))
            searchable_tokens = word_tokens(
                " ".join(str(row[key] or "") for key in row)
            )
            # Name and taxonomy are stronger than words occurring only in a
            # marketing description. Exact word matching also prevents
            # Vietnamese words such as "dép" from matching "đẹp".
            matches = sum(
                1
                + (4 if token in title_tokens else 0)
                + (3 if token in type_tokens else 0)
                for token in tokens
                if token in searchable_tokens
            )
            if len(tokens) == 1 and not (
                tokens & (title_tokens | type_tokens)
            ):
                continue
            comparable_title = (
                title.casefold().strip()
                if preserve_accents
                else self._normalize(title).strip()
            )
            comparable_query = raw_query if preserve_accents else normalized
            if comparable_query in comparable_title:
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
        resolved_type = self.resolve_product_type(query)
        if resolved_type:
            return self.recommend_same_type(
                product_type=resolved_type,
                exclude_codes=[],
                limit=limit,
            )
        return self.search(query=query, limit=limit)
