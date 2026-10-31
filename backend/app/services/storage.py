from __future__ import annotations

import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ("JPEG", ".jpg"),
    "image/png": ("PNG", ".png"),
    "image/webp": ("WEBP", ".webp"),
}


class LocalImageStorage:
    def __init__(
        self,
        upload_dir: Path,
        max_bytes: int,
        max_width: int = 4096,
        max_height: int = 4096,
        max_pixels: int = 12_000_000,
    ) -> None:
        self.upload_dir = upload_dir
        self.max_bytes = max_bytes
        self.max_width = max_width
        self.max_height = max_height
        self.max_pixels = max_pixels
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save_image(self, upload: UploadFile) -> str:
        declared_type = upload.content_type or ""
        expected = ALLOWED_IMAGE_TYPES.get(declared_type)
        if expected is None:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Type d'image non pris en charge.")

        content = await upload.read(self.max_bytes + 1)
        if not content or len(content) > self.max_bytes:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image trop volumineuse.")
        encoded, extension = self._decode_and_reencode(content, expected)

        identifier = uuid4()
        filename = f"{identifier}{extension}"
        final_path = self.upload_dir / filename
        temporary_path = self.upload_dir / f".{identifier}.tmp"
        try:
            temporary_path.write_bytes(encoded)
            temporary_path.replace(final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return f"/uploads/{filename}"

    def delete_image(self, photo_url: str) -> None:
        filename = Path(photo_url).name
        if photo_url != f"/uploads/{filename}":
            return
        target = self.upload_dir / filename
        if target.parent.resolve() != self.upload_dir.resolve():
            return
        target.unlink(missing_ok=True)

    def _decode_and_reencode(self, content: bytes, expected: tuple[str, str]) -> tuple[bytes, str]:
        expected_format, extension = expected
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as candidate:
                    if candidate.format != expected_format:
                        raise HTTPException(
                            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Le type declare ne correspond pas au contenu de l'image.",
                        )
                    self._validate_dimensions(candidate.width, candidate.height)
                    candidate.verify()

                with Image.open(BytesIO(content)) as decoded:
                    self._validate_dimensions(decoded.width, decoded.height)
                    safe_image = ImageOps.exif_transpose(decoded)
                    safe_image.load()
                    output = BytesIO()
                    self._save_without_metadata(safe_image, output, expected_format)
        except HTTPException:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Image corrompue ou non decodable.",
            ) from error

        encoded = output.getvalue()
        if not encoded or len(encoded) > self.max_bytes:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image reencodee trop volumineuse.")
        return encoded, extension

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("Dimensions image invalides.")
        if width > self.max_width or height > self.max_height or width * height > self.max_pixels:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Dimensions de l'image trop grandes.",
            )

    @staticmethod
    def _save_without_metadata(image: Image.Image, output: BytesIO, image_format: str) -> None:
        if image_format == "JPEG":
            image.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
            return
        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        safe_mode = "RGBA" if has_alpha else "RGB"
        if image_format == "PNG":
            image.convert(safe_mode).save(output, format="PNG", optimize=True)
            return
        image.convert(safe_mode).save(output, format="WEBP", quality=88, method=6)
