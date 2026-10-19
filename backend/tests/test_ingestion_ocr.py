"""① OCR landing: enablement path, graceful degradation, and boundary cases."""
import logging
import sys
import types
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.core.settings import get_settings
from app.services.knowledge_ingestion import ocr
from app.services.knowledge_ingestion.parsers import parse_document


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _enable_ocr(monkeypatch, **overrides):
    monkeypatch.setenv("OCR_ENABLED", "true")
    monkeypatch.setenv("OCR_PROVIDER", overrides.pop("provider", "rapidocr"))
    if "max_pages" in overrides:
        monkeypatch.setenv("OCR_MAX_PAGES", str(overrides.pop("max_pages")))
    get_settings.cache_clear()
    return get_settings()


def _page_image(label):
    image = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(image).text((10, 10), label, fill="black")
    return image


def _scanned_pdf(page_count=1):
    pages = [_page_image(f"scan page {index}") for index in range(page_count)]
    buffer = BytesIO()
    pages[0].save(buffer, format="PDF", save_all=True, append_images=pages[1:], resolution=72)
    return buffer.getvalue()


def _png_bytes(label="scan image"):
    buffer = BytesIO()
    _page_image(label).save(buffer, format="PNG")
    return buffer.getvalue()


def _install_fake_provider(monkeypatch, texts=("识别出的扫描文本",), calls=None):
    """Register a fake OCR backend under the default provider module name."""
    class _Engine:
        def __call__(self, image):
            if calls is not None:
                calls.append(image)
            return SimpleNamespace(txts=list(texts))

    module = types.ModuleType(ocr.provider_entry_point("rapidocr")[0])
    module.RapidOCR = lambda: _Engine()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


def test_default_configuration_keeps_todays_scan_behaviour():
    settings = get_settings()
    assert settings.ocr_enabled is False
    assert settings.ocr_provider == "rapidocr"
    assert settings.ocr_max_pages == 50

    units, warnings = parse_document("scan.pdf", _scanned_pdf(), "regulatory_policy")

    assert units == []
    assert warnings and any("OCR" in warning for warning in warnings)


def test_disabled_ocr_keeps_images_out_of_the_supported_formats():
    with pytest.raises(ValueError, match="Unsupported knowledge document format"):
        parse_document("scan.png", _png_bytes(), "regulatory_policy")



def test_enabled_ocr_without_provider_degrades_without_crashing(caplog, monkeypatch):
    _enable_ocr(monkeypatch)

    # alembic's fileConfig(disable_existing_loggers=True) can silence this logger mid-suite.
    logging.getLogger("app.services.knowledge_ingestion.ocr").disabled = False
    with caplog.at_level(logging.WARNING, logger="app.services.knowledge_ingestion.ocr"):
        units, warnings = parse_document("scan.pdf", _scanned_pdf(), "regulatory_policy")

    assert units == []
    joined = " ".join(warnings)
    assert "不可用" in joined
    assert "rapidocr_onnxruntime" in joined
    assert "ocr_enabled" in joined
    assert any("OCR unavailable" in record.message for record in caplog.records)


def test_enabled_ocr_without_provider_keeps_standalone_image_non_fatal(monkeypatch):
    _enable_ocr(monkeypatch)

    units, warnings = parse_document("scan.png", _png_bytes(), "regulatory_policy")

    assert units == []
    assert any("不可用" in warning for warning in warnings)


def test_enabled_ocr_runs_provider_and_keeps_page_locators(monkeypatch):
    _enable_ocr(monkeypatch)
    calls = []
    _install_fake_provider(monkeypatch, texts=("第一条监管口径", "第二条监管口径"), calls=calls)

    units, warnings = parse_document("scan.pdf", _scanned_pdf(), "regulatory_policy")

    assert len(calls) == 1
    assert units
    assert all(unit.source_page_no == 1 for unit in units)
    assert all(unit.metadata["locator"]["page_no"] == 1 for unit in units)
    assert all(unit.metadata["locator"]["block_id"] for unit in units)
    assert "第一条监管口径" in "".join(unit.content for unit in units)
    assert not any("不可用" in warning for warning in warnings)


def test_enabled_ocr_parses_standalone_image(monkeypatch):
    _enable_ocr(monkeypatch)
    _install_fake_provider(monkeypatch, texts=("图片中的监管文本",))

    units, warnings = parse_document("scan.jpg", _png_bytes(), "regulatory_policy")

    assert len(units) == 1
    assert units[0].source_page_no == 1
    assert units[0].metadata["locator"]["page_no"] == 1
    assert "图片中的监管文本" in units[0].content
    assert warnings == []


def test_empty_document_and_blank_scan_page_are_reported(monkeypatch):
    _enable_ocr(monkeypatch)

    units, warnings = parse_document("empty.png", b"", "regulatory_policy")
    assert units == []
    assert any("无法解码" in warning for warning in warnings)

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=420, height=595)
    buffer = BytesIO()
    writer.write(buffer)

    units, warnings = parse_document("blank.pdf", buffer.getvalue(), "regulatory_policy")
    assert units == []
    assert any("无可 OCR 图像" in warning for warning in warnings)


def test_scan_pages_beyond_ocr_max_pages_are_truncated_and_marked(monkeypatch):
    _enable_ocr(monkeypatch, max_pages=2)
    calls = []
    _install_fake_provider(monkeypatch, texts=("第 N 页文本",), calls=calls)

    units, warnings = parse_document("scan.pdf", _scanned_pdf(page_count=3), "regulatory_policy")

    assert len(calls) == 2, "only the pages inside ocr_max_pages may be OCR'd"
    assert any("截断" in warning and "ocr_max_pages=2" in warning for warning in warnings)
    assert all(unit.source_page_no <= 2 for unit in units)


def test_ocr_max_pages_zero_skips_everything_with_a_warning(monkeypatch):
    monkeypatch.setenv("OCR_ENABLED", "true")
    monkeypatch.setenv("OCR_MAX_PAGES", "0")
    get_settings.cache_clear()

    units, warnings = parse_document("scan.pdf", _scanned_pdf(page_count=2), "regulatory_policy")

    assert units == []
    assert any("ocr_max_pages=0" in warning for warning in warnings)


def test_provider_failure_on_one_image_keeps_other_pages(monkeypatch):
    _enable_ocr(monkeypatch)

    class _FlakyEngine:
        def __init__(self):
            self.calls = 0

        def __call__(self, image):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("synthetic provider failure")
            return SimpleNamespace(txts=["第二页识别成功"])

    module = types.ModuleType("rapidocr_onnxruntime")
    module.RapidOCR = lambda: _FlakyEngine()
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)

    units, warnings = parse_document("scan.pdf", _scanned_pdf(page_count=2), "regulatory_policy")

    assert any("识别失败" in warning for warning in warnings)
    assert any(unit.source_page_no == 2 for unit in units)


def test_run_ocr_returns_empty_result_without_images():
    result = ocr.run_ocr([])

    assert result.available is False
    assert result.texts == []
    assert result.warnings == []


def test_load_ocr_engine_reports_diagnosable_unavailable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)

    with pytest.raises(ocr.OcrProviderUnavailable) as failure:
        ocr.load_ocr_engine("rapidocr")

    message = str(failure.value)
    assert "rapidocr_onnxruntime" in message
    assert "ocr_enabled" in message
    assert "请安装" in message


def test_load_ocr_engine_reports_missing_entry_class(monkeypatch):
    module = types.ModuleType("rapidocr_onnxruntime")
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)

    with pytest.raises(ocr.OcrProviderUnavailable, match="未导出 RapidOCR"):
        ocr.load_ocr_engine("rapidocr")


def test_load_ocr_engine_reports_initialisation_failure(monkeypatch):
    module = types.ModuleType("rapidocr_onnxruntime")

    def _broken():
        raise RuntimeError("no onnx runtime")

    module.RapidOCR = _broken
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)

    with pytest.raises(ocr.OcrProviderUnavailable, match="初始化失败"):
        ocr.load_ocr_engine("rapidocr")


def test_extract_text_understands_provider_shapes():
    assert ocr._extract_text(SimpleNamespace(txts=["a", "b"])) == "a\nb"
    assert ocr._extract_text(SimpleNamespace(texts="single")) == "single"
    assert ocr._extract_text((SimpleNamespace(txts=["wrapped"]), 0.5)) == "wrapped"
    assert ocr._extract_text(["plain", "list"]) == "plain\nlist"
    assert ocr._extract_text(None) == ""
    assert ocr._extract_text(SimpleNamespace()) == ""


def test_run_ocr_uses_configured_provider_name(monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "paddleocr")
    get_settings.cache_clear()

    assert ocr.resolve_provider_name() == "paddleocr"
    assert ocr.resolve_provider_name("  RapidOCR ") == "rapidocr"
    assert ocr.provider_entry_point("paddleocr") == ("paddleocr", "PaddleOCR")


def test_page_images_decodes_embedded_raster():
    from pypdf import PdfReader

    page = PdfReader(BytesIO(_scanned_pdf())).pages[0]
    images = ocr.page_images(page)

    assert images
    assert all(image.size == (400, 200) for image in images)


def test_image_from_bytes_handles_undecodable_payload():
    assert ocr.image_from_bytes(b"") is None
    assert ocr.image_from_bytes(b"not-an-image") is None
    assert ocr.image_from_bytes(_png_bytes()).size == (400, 200)


def test_ocr_module_never_imports_providers_at_module_scope():
    source = ocr.__file__
    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    assert "import rapidocr_onnxruntime" not in text
    assert "import paddleocr" not in text
    assert "IMAGE_SUFFIXES" in text
