"""Bounded, local PDF page images for evidence review.

PDFium is not thread-safe, including operations on different documents. Every
PDFium object is created, used and closed under the same process-wide lock.
Rendered images stay in a small memory cache and are never written to disk.
"""

from __future__ import annotations

from collections import OrderedDict
import io
import math
import re
import threading
from typing import TYPE_CHECKING

import pypdfium2 as pdfium

if TYPE_CHECKING:
    from .store import ReportStore


_PDFIUM_LOCK = threading.RLock()
_MAX_EDGE = 1800
_MAX_CACHE_PAGES = 6
_MAX_PNG_BYTES = 12 * 1024 * 1024


class PageRenderer:
    """Render only existing, explicitly imported reports by ID and physical page."""

    def __init__(self, store: ReportStore) -> None:
        self.store = store
        self._cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()

    def clear(self) -> None:
        """Drop rendered data from memory after report removal or workspace reset."""
        with _PDFIUM_LOCK:
            self._cache.clear()

    def render(self, report_id: str, page: int) -> bytes:
        if not isinstance(report_id, str) or not re.fullmatch(r"[0-9a-f]{20}", report_id):
            raise ValueError("请从已导入的资料中选择年报，不能读取任意文件路径。")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError("请输入从 1 开始的 PDF 物理页码。")
        # Keep authorization and rendering together: deletion cannot complete
        # between checking the document and returning a cached source image.
        # The order is store lock -> PDFium lock; clear() never takes store lock.
        with self.store.lock:
            try:
                report = self.store.get(report_id)
            except ValueError:
                raise ValueError("这份年报已被移除，请重新选择或上传。") from None
            pages = report.get("pages", [])
            if page > len(pages):
                raise ValueError("PDF 物理页码超出这份年报的范围。")
            if pages[page - 1].get("number") != page:
                raise ValueError("年报页码索引不一致，请重新导入这份 PDF。")
            path = self.store.root / f"{report_id}.pdf"
            if path.is_symlink() or not path.is_file():
                raise ValueError("原始 PDF 不可用，请重新导入这份年报。")
            if path.resolve().parent != self.store.root.resolve():
                raise ValueError("原始 PDF 不在当前资料工作区，请重新导入。")
            with _PDFIUM_LOCK:
                key = report_id, page
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    return cached
                data = self._render_pdf(path, page)
                self._cache[key] = data
                self._cache.move_to_end(key)
                while len(self._cache) > _MAX_CACHE_PAGES:
                    self._cache.popitem(last=False)
                return data

    @staticmethod
    def _render_pdf(path, number: int) -> bytes:
        document = source_page = bitmap = source_image = image = None
        try:
            document = pdfium.PdfDocument(str(path))
            if number > len(document):
                raise ValueError("page index mismatch")
            source_page = document[number - 1]
            width, height = source_page.get_size()
            if not all(math.isfinite(size) and 0 < size <= 10_000_000 for size in (width, height)):
                raise ValueError("invalid source page size")
            scale = min(3.0, (_MAX_EDGE - 1) / max(width, height))
            bitmap = source_page.render(scale=scale, may_draw_forms=False,
                                        fill_color=(255, 255, 255, 255))
            source_image = bitmap.to_pil()
            # A detached RGB copy avoids retaining PDFium's underlying bitmap.
            image = source_image.convert("RGB")
            if max(image.size) > _MAX_EDGE:
                image.thumbnail((_MAX_EDGE, _MAX_EDGE))
            output = io.BytesIO()
            image.save(output, format="PNG", compress_level=6)
            data = output.getvalue()
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > _MAX_PNG_BYTES:
                raise ValueError("invalid rendered output")
            return data
        except Exception:
            raise ValueError("原文页面无法显示，请尝试打开原 PDF，或重新导出后上传。") from None
        finally:
            # Close each resource even if another close unexpectedly fails. The
            # caller holds the global PDFium lock through the entire cleanup.
            for resource in (image, source_image, bitmap, source_page, document):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass
