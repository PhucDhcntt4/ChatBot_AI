"""Compatibility entry point for building image vectors in Qdrant."""

from app.scripts.sync_image_vectors_to_qdrant import main as sync_qdrant


def main(product_codes: list[str] | tuple[str, ...] | None = None) -> dict[str, int]:
    result = sync_qdrant(product_codes=product_codes)
    response = {
        "created": result["synced"],
        "skipped": result["unchanged"],
        "failed": result["failed"],
        "deleted": result["deleted"],
        "qdrant_synced": result["synced"],
    }
    if response["failed"]:
        raise RuntimeError(
            "Có ảnh tạo vector thất bại. Kiểm tra log và chạy lại tác vụ."
        )
    return response


if __name__ == "__main__":
    print(main())
