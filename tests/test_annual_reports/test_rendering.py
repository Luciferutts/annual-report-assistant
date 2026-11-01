"""Source-page image correctness, retention bounds and imported-file isolation."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
from pathlib import Path
import shutil
import threading
import time

from PIL import Image
from pypdf import PdfReader
import pytest

from openharness.annual_reports import rendering
from openharness.annual_reports.store import ReportStore


@pytest.fixture(scope="module")
def official_pdf():
    path = Path(__file__).parents[2] / "data/annual_reports_demo/moutai-2024.pdf"
    if not path.is_file():
        pytest.skip("Official annual-report demonstration PDF is not installed")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open("rb") as handle:
        page_count = len(PdfReader(handle).pages)
    return path, digest[:20], page_count


def imported_store(root, official_pdf):
    source, report_id, page_count = official_pdf
    store = ReportStore(root)
    shutil.copyfile(source, store.root / f"{report_id}.pdf")
    store.reports[report_id] = {
        "id": report_id, "filename": "贵州茅台2024年年度报告.pdf", "year": 2024,
        "company": "贵州茅台酒股份有限公司", "page_count": page_count,
        "pages": [{"number": number, "text": ""} for number in range(1, page_count + 1)],
        "metrics": [],
    }
    return store, report_id


@pytest.fixture
def imported(tmp_path, official_pdf):
    store, report_id = imported_store(tmp_path / "workspace", official_pdf)
    return store, report_id, rendering.PageRenderer(store)


def test_real_annual_report_page_is_legible_bounded_png_without_disk_image(imported):
    store, report_id, renderer = imported
    png = renderer.render(report_id, 5)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) < 12 * 1024 * 1024
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        assert 1000 <= max(image.size) <= 1800
        assert min(image.size) > 500
        grayscale = image.convert("L")
        try:
            darkest, lightest = grayscale.getextrema()
            assert darkest < 100  # The table/text did render, not a white placeholder.
            assert lightest > 245  # The page did render, not a black viewer screen.
        finally:
            grayscale.close()
    assert not list(store.root.glob("*.png"))
    assert sorted(path.suffix for path in store.root.iterdir()) == [".pdf"]


@pytest.mark.parametrize("report_id", ["../outside", "/etc/passwd", "a" * 19, "G" * 20, None])
def test_renderer_rejects_paths_and_invalid_document_ids(imported, report_id):
    _, _, renderer = imported
    with pytest.raises(ValueError, match="已导入|任意文件"):
        renderer.render(report_id, 5)


def test_renderer_requires_an_imported_document_even_for_valid_id(imported):
    _, _, renderer = imported
    with pytest.raises(ValueError, match="移除|上传"):
        renderer.render("b" * 20, 5)


@pytest.mark.parametrize("page", [0, -1, 999, True, "5", None])
def test_renderer_rejects_invalid_or_out_of_range_physical_pages(imported, page):
    _, report_id, renderer = imported
    with pytest.raises(ValueError, match="页码"):
        renderer.render(report_id, page)


def test_renderer_does_not_serve_cached_document_after_deletion(imported, monkeypatch):
    store, report_id, renderer = imported
    assert renderer.render(report_id, 5).startswith(b"\x89PNG")
    store.delete(report_id)
    monkeypatch.setattr(rendering.pdfium, "PdfDocument", lambda *args: pytest.fail("Deleted PDF was reopened"))
    with pytest.raises(ValueError, match="移除"):
        renderer.render(report_id, 5)


def test_renderer_rechecks_source_file_before_returning_cache(imported):
    store, report_id, renderer = imported
    renderer.render(report_id, 5)
    (store.root / f"{report_id}.pdf").unlink()
    with pytest.raises(ValueError, match="原始 PDF 不可用"):
        renderer.render(report_id, 5)


def test_renderer_refuses_symlink_outside_workspace_even_after_caching(imported, official_pdf):
    store, report_id, renderer = imported
    renderer.render(report_id, 5)
    path = store.root / f"{report_id}.pdf"
    path.unlink()
    path.symlink_to(official_pdf[0])
    with pytest.raises(ValueError, match="原始 PDF 不可用"):
        renderer.render(report_id, 5)


def test_six_page_cache_evicts_oldest_and_clear_releases_cached_data(imported, monkeypatch):
    _, report_id, renderer = imported
    original = rendering.pdfium.PdfDocument
    opened = []

    def document(path):
        opened.append(path)
        return original(path)

    monkeypatch.setattr(rendering.pdfium, "PdfDocument", document)
    first = renderer.render(report_id, 1)
    assert renderer.render(report_id, 1) == first
    assert len(opened) == 1
    for page in range(2, 8):
        renderer.render(report_id, page)
    assert len(opened) == 7
    renderer.render(report_id, 2)
    assert len(opened) == 7  # A recently retained page remains cached.
    renderer.render(report_id, 1)
    assert len(opened) == 8  # The seventh distinct page evicted the oldest.
    renderer.clear()
    renderer.render(report_id, 1)
    assert len(opened) == 9


def test_unexpected_renderer_error_is_chinese_and_hides_paths(imported, monkeypatch):
    store, report_id, renderer = imported

    def fail(path):
        raise RuntimeError("private-renderer-details " + str(path))

    monkeypatch.setattr(rendering.pdfium, "PdfDocument", fail)
    with pytest.raises(ValueError, match="原文页面无法显示") as error:
        renderer.render(report_id, 5)
    assert str(store.root) not in str(error.value)
    assert "private-renderer-details" not in str(error.value)


def test_pdfium_is_serialized_across_different_workspaces(tmp_path, official_pdf, monkeypatch):
    first, report_id = imported_store(tmp_path / "first", official_pdf)
    second, _ = imported_store(tmp_path / "second", official_pdf)
    renderers = [rendering.PageRenderer(first), rendering.PageRenderer(second)]
    original = rendering.pdfium.PdfDocument
    counter_lock = threading.Lock()
    active = [0]
    peak = [0]

    class Document:
        def __init__(self, path):
            with counter_lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
                if active[0] > 1:
                    active[0] -= 1
                    raise RuntimeError("Concurrent PDFium access must not happen")
            time.sleep(0.02)
            self.document = original(path)

        def __len__(self):
            return len(self.document)

        def __getitem__(self, index):
            return self.document[index]

        def close(self):
            self.document.close()
            with counter_lock:
                active[0] -= 1

    monkeypatch.setattr(rendering.pdfium, "PdfDocument", Document)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(renderer.render, report_id, 5) for renderer in renderers]
        images = [future.result(timeout=15) for future in futures]
    assert all(image.startswith(b"\x89PNG") for image in images)
    assert peak[0] == 1
    assert active[0] == 0
