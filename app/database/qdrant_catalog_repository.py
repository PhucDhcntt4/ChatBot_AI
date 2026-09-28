import random
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.config import (
    IMAGE_QDRANT_API_KEY,
    IMAGE_QDRANT_URL,
    QDRANT_CATALOG_COLLECTION,
)
from app.database.product_repository import ProductRepository


class QdrantCatalogRepository(ProductRepository):
    """Product catalog backed by Qdrant payloads.

    The one-dimensional vector only satisfies Qdrant's collection contract.
    Product/image similarity remains in the dedicated CLIP collection.
    """

    provider = "qdrant"
    KIND = "bot_product_catalog"
    DIMENSION = 1

    def __init__(self, collection: str | None = None):
        collection_name = (
            collection or QDRANT_CATALOG_COLLECTION
        ).strip()
        if not IMAGE_QDRANT_URL or not collection_name:
            raise ValueError("Thiếu cấu hình Qdrant catalog")
        url = httpx.URL(IMAGE_QDRANT_URL)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("URL Qdrant catalog không hợp lệ")
        self.path = "/collections/" + quote(collection_name, safe="")

    def request(self, method: str, path: str, **kwargs):
        headers = {}
        if IMAGE_QDRANT_API_KEY:
            headers["api-key"] = IMAGE_QDRANT_API_KEY
        with httpx.Client(
            timeout=httpx.Timeout(30, connect=5),
            headers=headers,
            follow_redirects=False,
        ) as client:
            response = client.request(
                method,
                IMAGE_QDRANT_URL + path,
                **kwargs,
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict) or body.get("status") != "ok":
            raise RuntimeError("Qdrant trả dữ liệu catalog không hợp lệ")
        return body.get("result")

    @classmethod
    def point_id(cls, product_code: str) -> str:
        code = product_code.strip().upper()
        return str(uuid5(NAMESPACE_URL, f"donghai-product:{code}"))

    @classmethod
    def _validate_collection(cls, info: dict[str, Any]) -> None:
        vectors = info["config"]["params"]["vectors"]
        if (
            vectors.get("size") != cls.DIMENSION
            or vectors.get("distance") != "Cosine"
        ):
            raise ValueError(
                "Collection catalog phải có vector 1 chiều, distance=Cosine"
            )

    def ensure_collection(self) -> None:
        try:
            info = self.request("GET", self.path)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            self.request(
                "PUT",
                self.path,
                json={
                    "vectors": {
                        "size": self.DIMENSION,
                        "distance": "Cosine",
                    },
                    "hnsw_config": {"m": 0},
                },
            )
            info = self.request("GET", self.path)
        self._validate_collection(info)
        for field in (
            "kind",
            "product_code",
            "product_type",
            "status",
            "variant_skus",
        ):
            self.request(
                "PUT",
                self.path + "/index",
                params={"wait": "true"},
                json={"field_name": field, "field_schema": "keyword"},
            )

    def ready(self) -> dict[str, Any]:
        info = self.request("GET", self.path)
        self._validate_collection(info)
        if info.get("status") not in {"green", "yellow"}:
            raise RuntimeError("Collection catalog Qdrant chưa sẵn sàng")
        return info

    def upsert_snapshots(self, snapshots: list[dict[str, Any]]) -> int:
        points = []
        for snapshot in snapshots:
            code = str(snapshot.get("product_code") or "").strip().upper()
            if not code:
                continue
            payload = {**snapshot, "kind": self.KIND, "product_code": code}
            points.append({
                "id": self.point_id(code),
                "vector": [1.0],
                "payload": payload,
            })
        for start in range(0, len(points), 100):
            self.request(
                "PUT",
                self.path + "/points",
                params={"wait": "true"},
                json={"points": points[start:start + 100]},
            )
        return len(points)

    def delete_codes(self, product_codes: list[str]) -> None:
        ids = [self.point_id(code) for code in product_codes if code.strip()]
        if not ids:
            return
        self.request(
            "POST",
            self.path + "/points/delete",
            params={"wait": "true"},
            json={"points": ids},
        )

    def _scroll_payloads(
        self,
        conditions: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        must = [{"key": "kind", "match": {"value": self.KIND}}]
        must.extend(conditions or [])
        offset = None
        seen_offsets: set[str] = set()
        payloads: list[dict[str, Any]] = []
        while True:
            query: dict[str, Any] = {
                "filter": {"must": must},
                "limit": 256,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                query["offset"] = offset
            result = self.request(
                "POST",
                self.path + "/points/scroll",
                json=query,
            )
            points = result.get("points")
            if not isinstance(points, list):
                raise RuntimeError("Qdrant trả danh sách catalog không hợp lệ")
            for point in points:
                payload = point.get("payload") or {}
                if payload.get("kind") == self.KIND:
                    payloads.append(payload)
            next_offset = result.get("next_page_offset")
            if next_offset is None:
                return payloads
            marker = str(next_offset)
            if not points or marker in seen_offsets:
                raise RuntimeError("Qdrant trả cursor catalog bị lặp")
            seen_offsets.add(marker)
            offset = next_offset

    def _payload_by_code(self, product_code: str) -> dict[str, Any] | None:
        code = product_code.strip().upper()
        if not code:
            return None
        result = self.request(
            "POST",
            self.path + "/points/scroll",
            json={
                "filter": {"must": [
                    {"key": "kind", "match": {"value": self.KIND}},
                    {"key": "product_code", "match": {"value": code}},
                ]},
                "limit": 2,
                "with_payload": True,
                "with_vector": False,
            },
        )
        points = result.get("points") or []
        if len(points) > 1:
            raise RuntimeError(f"Catalog Qdrant trùng mã sản phẩm {code}")
        return (points[0].get("payload") or {}) if points else None

    def health(self) -> dict[str, int]:
        payloads = self._scroll_payloads()
        return {
            "products": len(payloads),
            "variants": sum(len(item.get("variants") or []) for item in payloads),
            "images": sum(len(item.get("images") or []) for item in payloads),
        }

    def catalog_codes(self) -> list[str]:
        return [
            str(item.get("product_code") or "").strip().upper()
            for item in self._scroll_payloads()
            if str(item.get("product_code") or "").strip()
        ]

    def image_records(
        self,
        product_codes: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        requested = {
            str(code).strip().upper()
            for code in (product_codes or []) if str(code).strip()
        }
        records = []
        for payload in self._scroll_payloads([
            {"key": "status", "match": {"value": "ACTIVE"}},
        ]):
            code = str(payload.get("product_code") or "").strip().upper()
            if requested and code not in requested:
                continue
            for image in payload.get("images") or []:
                if (
                    image.get("is_active") is not False
                    and image.get("local_path")
                    and image.get("source_url")
                ):
                    records.append({
                        **image,
                        "product_code": code,
                        "title": payload.get("title"),
                        "product_type": payload.get("product_type"),
                    })
        return records

    def product_types(self, active_only: bool = True) -> list[str]:
        conditions = (
            [{"key": "status", "match": {"value": "ACTIVE"}}]
            if active_only else []
        )
        return sorted({
            str(item.get("product_type") or "").strip()
            for item in self._scroll_payloads(conditions)
            if str(item.get("product_type") or "").strip()
        })

    def public_info(self, product_code: str) -> dict[str, Any] | None:
        payload = self._payload_by_code(product_code)
        if not payload:
            return None
        value = payload.get("public_info")
        return value if isinstance(value, dict) else None

    def _search_rows(self):
        return [
            {
                "product_code": item.get("product_code"),
                "title": item.get("title"),
                "product_type": item.get("product_type"),
                "description": item.get("description"),
                "vendor": item.get("vendor"),
                "material": item.get("material"),
                "sole": item.get("sole"),
                "height": item.get("height"),
                "status": item.get("status"),
            }
            for item in self._scroll_payloads()
        ]

    def reference_products(
        self,
        product_type: str | None = None,
        limit: int = 5,
        images_per_product: int = 3,
    ) -> list[dict[str, Any]]:
        conditions = [{"key": "status", "match": {"value": "ACTIVE"}}]
        if product_type:
            conditions.append({
                "key": "product_type",
                "match": {"value": product_type},
            })
        references = []
        for payload in self._scroll_payloads(conditions)[:limit]:
            product = payload.get("public_info") or {}
            if product.get("image_urls"):
                references.append({
                    "product_code": product.get("product_code"),
                    "title": product.get("product_name"),
                    "product_type": product.get("product_type"),
                    "image_urls": product["image_urls"][:images_per_product],
                })
        return references

    def recommend_same_type(
        self,
        product_type: str,
        exclude_codes: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        payloads = self._scroll_payloads([
            {"key": "status", "match": {"value": "ACTIVE"}},
            {"key": "product_type", "match": {"value": product_type}},
        ])
        excluded = {code.strip().upper() for code in exclude_codes}
        candidates = [
            item.get("public_info")
            for item in payloads
            if item.get("product_code") not in excluded
            and isinstance(item.get("public_info"), dict)
        ]
        random.shuffle(candidates)
        return candidates[:limit]

    def catalog_page(
        self,
        search: str = "",
        product_type: str = "",
        status: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        keyword = self._normalize(search).strip()
        selected_type = product_type.strip()
        selected_status = status.strip().upper()
        all_payloads = self._scroll_payloads()
        product_types = sorted({
            str(item.get("product_type") or "").strip()
            for item in all_payloads
            if str(item.get("product_type") or "").strip()
        })
        product_statuses = sorted({
            str(item.get("status") or "").strip().upper()
            for item in all_payloads
            if str(item.get("status") or "").strip()
        })
        filtered = []
        for item in all_payloads:
            if selected_type and item.get("product_type") != selected_type:
                continue
            if selected_status and str(item.get("status") or "").upper() != selected_status:
                continue
            searchable = self._normalize(
                f"{item.get('product_code', '')} {item.get('title', '')} "
                f"{item.get('product_type', '')}"
            )
            if keyword and keyword not in searchable:
                continue
            filtered.append(item)
        filtered.sort(
            key=lambda item: (
                str(item.get("updated_at") or ""),
                str(item.get("product_code") or ""),
            ),
            reverse=True,
        )
        products = []
        for item in filtered[offset:offset + limit]:
            summary = dict(item.get("summary") or {})
            summary.setdefault("vendor", item.get("vendor"))
            summary.setdefault("status", item.get("status"))
            public_info = item.get("public_info") or {}
            image_urls = public_info.get("image_urls") or []
            if image_urls:
                summary.setdefault("image_url", image_urls[0])
            elif item.get("images"):
                first_image = next(
                    (
                        image for image in item["images"]
                        if image.get("is_active", True) and image.get("source_url")
                    ),
                    None,
                )
                if first_image:
                    summary.setdefault("image_url", first_image["source_url"])
            products.append(summary)
        return {
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "product_types": product_types,
            "product_statuses": product_statuses,
            "products": products,
        }

    def catalog_detail(self, product_code: str) -> dict[str, Any] | None:
        payload = self._payload_by_code(product_code)
        detail = payload.get("detail") if payload else None
        return detail if isinstance(detail, dict) else None
