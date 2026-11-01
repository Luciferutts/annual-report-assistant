"""Private, local storage for documents explicitly uploaded to this app."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from .analysis import build_comparison
from .extraction import extract_report

MAX_UPLOAD = 25 * 1024 * 1024
METRIC_KEYS = {
    "revenue", "profit_parent", "profit_deducted", "operating_cashflow",
    "total_assets", "equity_parent",
}
METRIC_LABELS = {
    "revenue": "营业收入", "profit_parent": "归母净利润",
    "profit_deducted": "扣非归母净利润", "operating_cashflow": "经营现金流净额",
    "total_assets": "总资产", "equity_parent": "归母净资产",
}
UNITS = {"元", "千元", "万元", "百万元", "亿元"}
NUMBER = re.compile(r"[-−－]?(?:[（(]\s*[\d,，]+(?:\.\d+)?\s*[）)]|[\d,，]+(?:\.\d+)?)")


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
    temporary.replace(path)


def _decimal(raw: Any) -> Decimal:
    if isinstance(raw, bool) or raw is None:
        raise ValueError("请输入原文中的完整金额，不要输入百分比或空值。")
    text = str(raw).strip().replace(",", "").replace("，", "").replace("−", "-").replace("－", "-")
    text = text.replace("（", "(").replace("）", ")")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if len(text) > 48 or not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        raise ValueError("金额应为数字，可包含千分位和小数；请保留原文单位。")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("金额格式不正确。") from exc
    if not number.is_finite() or abs(number) > Decimal("1e22"):
        raise ValueError("金额超出支持范围，请核对原文。")
    return number


def evidence_for_value(text: str, value: Decimal) -> str:
    """Require a literal source amount; human review cannot create unsupported numbers."""
    for match in NUMBER.finditer(text):
        if text[match.end():].lstrip().startswith(("%", "％")):
            continue
        try:
            found = _decimal(match.group())
        except ValueError:
            continue
        if found == value:
            start = max(0, match.start() - 240)
            end = min(len(text), match.end() + 240)
            return text[start:end].strip()
    raise ValueError("在所选 PDF 页未找到这个金额。请核对数字和物理页码，金额保持原文单位。")


class ReportStore:
    """At most two active reports, no access to arbitrary user paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.lock = threading.RLock()
        self.reports: dict[str, dict] = {}
        for path in sorted(self.root.glob("*.json")):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                report_id = report.get("id", "")
                if re.fullmatch(r"[0-9a-f]{20}", report_id) and (self.root / f"{report_id}.pdf").is_file():
                    self.reports[report_id] = report
            except (ValueError, OSError, AttributeError):
                continue

    def documents(self) -> list[dict]:
        with self.lock:
            return json.loads(json.dumps(list(self.reports.values()), ensure_ascii=False))

    def get(self, report_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{20}", report_id):
            raise ValueError("未找到这份年报，请重新选择。")
        with self.lock:
            if report_id not in self.reports:
                raise ValueError("这份年报已被移除，请刷新页面。")
            return json.loads(json.dumps(self.reports[report_id], ensure_ascii=False))

    def fingerprint(self) -> str:
        with self.lock:
            payload = json.dumps(
                [{"id": r["id"], "metrics": r.get("metrics", []), "year": r.get("year")}
                 for r in self.reports.values()], sort_keys=True, ensure_ascii=False,
            ).encode()
        return hashlib.sha256(payload).hexdigest()

    def state(self) -> dict:
        reports = self.documents()
        metadata = [{key: value for key, value in report.items() if key not in {"pages", "audit"}}
                    for report in reports]
        comparison = None
        error = ""
        if reports:
            try:
                comparison = build_comparison(reports)
            except ValueError as exc:
                error = str(exc)
        return {"reports": metadata, "comparison": comparison, "comparison_error": error}

    def add_pdf(self, data: bytes, filename: str, source_url: str = "") -> dict:
        if not data or len(data) > MAX_UPLOAD:
            raise ValueError("请选择不超过 25 MB 的 PDF 年报。")
        if not data.lstrip().startswith(b"%PDF-"):
            raise ValueError("文件内容不是 PDF，请上传正式年报的 PDF 文件。")
        safe_name = Path(filename.replace("\\", "/")).name
        safe_name = "".join(c for c in safe_name if ord(c) >= 32)[:160]
        if not safe_name.lower().endswith(".pdf"):
            raise ValueError("只支持 PDF 年报文件。")
        report_id = hashlib.sha256(data).hexdigest()[:20]
        with self.lock:
            if report_id in self.reports:
                return self.get(report_id)
            if len(self.reports) >= 2:
                raise ValueError("当前工作区最多保留两份年报，请先移除一份再上传。")
            path = self.root / f"{report_id}.pdf"
            path.write_bytes(data)
            os.chmod(path, 0o600)
            try:
                report = extract_report(path, filename=safe_name, source_url=source_url)
                report["id"] = report_id
                report["created_at"] = time.time()
                report["audit"] = []
                _write_json(self.root / f"{report_id}.json", report)
            except Exception:
                path.unlink(missing_ok=True)
                raise
            self.reports[report_id] = report
            return self.get(report_id)

    def confirm_metric(self, report_id: str, update: dict) -> None:
        key = update.get("key")
        if key not in METRIC_KEYS:
            raise ValueError("请选择支持的财务指标。")
        if update.get("status") != "confirmed":
            raise ValueError("请核对原文后明确确认这条数据。")
        page = update.get("page")
        year = update.get("year")
        if isinstance(page, bool) or not isinstance(page, int):
            raise ValueError("请输入 PDF 阅读器中的物理页码。")
        if isinstance(year, bool) or not isinstance(year, int):
            raise ValueError("请选择指标对应的年度。")
        unit = update.get("unit")
        if unit not in UNITS:
            raise ValueError("请选择原文金额单位；本系统将统一换算为元计算。")
        if update.get("currency") != "CNY":
            raise ValueError("第一版仅支持人民币年报，请确认币种为人民币。")
        number = _decimal(update.get("value"))
        with self.lock:
            report = self.get(report_id)
            pages = report.get("pages", [])
            if page < 1 or page > len(pages):
                raise ValueError("PDF 页码超出这份年报的范围。")
            report_year = report.get("year")
            if report_year is None or year not in {report_year, report_year - 1}:
                raise ValueError("只可核对本报告年度和上一年度的数据。")
            prior = next((metric for metric in report.get("metrics", [])
                          if metric.get("key") == key and metric.get("year") == year), None)
            scope = update.get("scope", (prior or {}).get("scope", "unknown"))
            if scope not in {"consolidated", "parent"}:
                raise ValueError("请确认原文是合并口径还是母公司口径。正式对比使用合并口径。")
            page_text = pages[page - 1]["text"]
            evidence = evidence_for_value(page_text, number)
            new = {
                **(prior or {}), "key": key, "label": METRIC_LABELS[key], "year": year,
                "value": format(number, "f"), "raw_value": str(update["value"]),
                "unit": unit, "currency": "CNY", "page": page,
                "evidence": evidence, "scope": scope, "status": "confirmed",
                "reviewed_at": time.time(), "review_method": "human_source_check",
            }
            if prior and "original_extraction" not in prior:
                new["original_extraction"] = {k: prior.get(k) for k in (
                    "value", "raw_value", "unit", "page", "evidence", "status", "scope")}
            report["metrics"] = [m for m in report.get("metrics", [])
                                 if not (m.get("key") == key and m.get("year") == year)] + [new]
            report.setdefault("audit", []).append({
                "at": time.time(), "action": "confirm_metric", "key": key, "year": year,
                "before": prior, "after": {k: new[k] for k in (
                    "value", "unit", "page", "currency", "scope", "status")},
            })
            _write_json(self.root / f"{report_id}.json", report)
            self.reports[report_id] = report

    def delete(self, report_id: str) -> None:
        with self.lock:
            self.get(report_id)
            for suffix in (".pdf", ".json", ".tmp"):
                (self.root / f"{report_id}{suffix}").unlink(missing_ok=True)
            del self.reports[report_id]
