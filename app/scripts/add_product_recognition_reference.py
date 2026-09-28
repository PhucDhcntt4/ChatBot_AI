"""Add a curated local image used only for product visual recognition."""

import argparse
from pathlib import Path

from app.services.product_recognition_reference_service import (
    add_recognition_reference,
)


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=True, help="Product code, for example SHLN9")
    parser.add_argument("--image", required=True, type=Path, help="JPEG/PNG/WebP reference image")
    parser.add_argument("--color", default="", help="Optional product color")
    args = parser.parse_args()
    source_path = args.image.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    result = add_recognition_reference(
        product_code=args.code,
        image_bytes=source_path.read_bytes(),
        color=args.color,
    )
    print(result)
    return result


if __name__ == "__main__":
    main()
