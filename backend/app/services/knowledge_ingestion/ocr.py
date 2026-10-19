"""Runtime-optional OCR support for scanned knowledge documents.

OCR backends (``rapidocr_onnxruntime`` by default, ``paddleocr`` optionally) are
extras that are deliberately not part of the locked dependency set, and a
deployment may run offline without them installed.  Every entry point in this
module therefore degrades gracefully: a missing or broken provider yields a
diagnosable warning instead of an exception, so ``ocr_enabled`` can be switched
on without breaking ordinary text ingestion.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from app.core.settings import get_settings

logger = logging.getLogger("app.services.knowledge_ingestion.ocr")

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"})

_PROVIDER_ENTRY_POINTS: dict[str, tuple[str, str]] = {
    "rapidocr": ("rapidocr_onnxruntime", "RapidOCR"),
    "rapidocr-onnxruntime": ("rapidocr_onnxruntime", "RapidOCR"),
    "rapidocr_onnxruntime": ("rapidocr_onnxruntime", "RapidOCR"),
    "paddleocr": ("paddleocr", "PaddleOCR"),
}


class OcrProviderUnavailable(RuntimeError):
    """The configured OCR provider cannot be imported or initialised."""


@dataclass
class OcrBatchResult:
    provider: str
    available: bool = False
    texts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_provider_name(provider: str | None = None) -> str:
    return str(provider or get_settings().ocr_provider or "rapidocr").strip().lower()


def provider_entry_point(provider: str) -> tuple[str, str]:
    return _PROVIDER_ENTRY_POINTS.get(provider, (provider, "RapidOCR"))


def load_ocr_engine(provider: str | None = None) -> Any:
    """Import and construct the configured OCR engine, or raise a diagnosable error."""
    name = resolve_provider_name(provider)
    module_name, class_name = provider_entry_point(name)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise OcrProviderUnavailable(
            f"OCR provider '{name}' 不可用：无法导入可选依赖 {module_name}（{exc}）；OCR 已跳过。"
            f"请安装 {module_name}，或改用其它 ocr_provider，或将 ocr_enabled 设为 false。"
        ) from exc
    factory = getattr(module, class_name, None)
    if factory is None:
        raise OcrProviderUnavailable(f"OCR provider '{name}' 不可用：{module_name} 未导出 {class_name} 入口类。")
    try:
        return factory()
    except Exception as exc:  # provider initialisation must never break ingestion
        raise OcrProviderUnavailable(f"OCR provider '{name}' 初始化失败：{type(exc).__name__}: {exc}") from exc


def load_engine_or_warn(provider: str | None = None) -> tuple[Any | None, str | None]:
    """Load the OCR engine once per document, logging any graceful degradation."""
    name = resolve_provider_name(provider)
    try:
        return load_ocr_engine(name), None
    except OcrProviderUnavailable as exc:
        logger.warning("OCR unavailable (provider=%s): %s", name, exc)
        return None, str(exc)


def run_ocr(images: list[Any], *, provider: str | None = None, engine: Any | None = None) -> OcrBatchResult:
    """Recognise text from ``images``; always returns, never raises on provider failure."""
    name = resolve_provider_name(provider)
    result = OcrBatchResult(provider=name)
    if not images:
        return result
    if engine is None:
        engine, error = load_engine_or_warn(name)
        if engine is None:
            if error:
                result.warnings.append(error)
            return result
    result.available = True
    for position, image in enumerate(images, 1):
        try:
            result.texts.append(_extract_text(engine(image)))
        except Exception as exc:  # one bad page must not abort the document
            logger.warning("OCR failed on image %s: %s", position, exc, exc_info=True)
            result.texts.append("")
            result.warnings.append(f"OCR 第 {position} 张图像识别失败：{type(exc).__name__}: {exc}")
    return result


def _extract_text(raw: Any) -> str:
    if isinstance(raw, tuple) and raw:
        raw = raw[0]
    if raw is None:
        return ""
    for attribute in ("txts", "texts"):
        values = getattr(raw, attribute, None)
        if isinstance(values, str):
            return values
        if values:
            return "\n".join(str(value) for value in values if value)
    if isinstance(raw, (list, tuple)):
        return "\n".join(str(value) for value in raw if value)
    for attribute in ("text", "txt"):
        value = getattr(raw, attribute, None)
        if value:
            return str(value)
    return ""


def page_images(page: Any) -> list[Any]:
    """Return the embedded raster images of a pypdf page as PIL images."""
    try:
        embedded = list(getattr(page, "images", []) or [])
    except Exception:
        logger.warning("reading embedded images from a PDF page failed", exc_info=True)
        return []
    images = []
    for entry in embedded:
        image = _decode_embedded_image(entry)
        if image is not None:
            images.append(image)
    return images


def _decode_embedded_image(entry: Any) -> Any | None:
    data = getattr(entry, "data", None)
    if data:
        image = image_from_bytes(data)
        if image is not None:
            return image
    return getattr(entry, "image", None)


def image_from_bytes(data: bytes) -> Any | None:
    if not data:
        return None
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow is not installed; scanned images cannot be decoded for OCR")
        return None
    try:
        return Image.open(BytesIO(data))
    except Exception:
        logger.warning("decoding image bytes for OCR failed", exc_info=True)
        return None
