"""Local, conservative extraction of Chinese annual-report headline data.

Extraction produces review candidates, never trusted financial facts. Numbers
keep their original units and exact source rows; calculations live elsewhere.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


METRIC_LABELS = {
    "revenue": "营业收入",
    "profit_parent": "归母净利润",
    "profit_deducted": "扣非归母净利润",
    "operating_cashflow": "经营现金流净额",
    "total_assets": "总资产",
    "equity_parent": "归母净资产",
}
MAX_PAGES = 500
MAX_FILE_BYTES = 25 * 1024 * 1024
_NUMBER = re.compile(
    r"(?<![\d.])(?:[（(]\s*)?[+\-−]?\d[\d,，]*(?:\.\d+)?\s*[)）]?(?:[%％])?"
    r"|(?<!\S)[—–\-]{1,2}(?!\S)"
    r"|(?<!\S)(?:不适用|N/A|n/a)(?!\S)"
)
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?:\s*年(?:末|度)?)?(?!\d)")
_UNIT = re.compile(r"(?:金额)?单位\s*[:：]?\s*(?:人民币\s*)?(亿元|百万元|万元|千元|元)")
_CURRENCY = re.compile(r"币种\s*[:：]?\s*(人民币|美元|港元|港币|欧元|日元)")
_STARTS = (
    "营业收入", "归属于上市公司股东", "归属于母公司", "归属母公司", "归属于挂牌公司股东",
    "经营活动产生的现金流量", "总资产", "资产总计",
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("︰", "：")


def parse_decimal(value: str) -> str | None:
    """Normalize a source number without float conversion or unit conversion."""
    cleaned = re.sub(r"\s+", "", value).replace(",", "").replace("，", "")
    cleaned = cleaned.replace("−", "-").replace("（", "(").replace("）", ")")
    if cleaned in {"", "-", "--", "—", "–", "/", "不适用", "N/A"} or "%" in cleaned:
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return format(number, "f")


def _looks_like_row(line: str) -> bool:
    text = _compact(line)
    text = re.sub(r"^[一二三四五六七八九十、.．()（）\d]+", "", text)
    if text.startswith(_STARTS):
        return True
    # Narrow printed columns often split a label before even its first word
    # completes (e.g. "归属于上市公" on the 2023 example's first line).
    label_prefix = re.split(r"[\d,，]", text, maxsplit=1)[0]
    return len(label_prefix) >= 5 and any(stem.startswith(label_prefix) for stem in _STARTS)


def _metric_key(row: str) -> str | None:
    # Numeric cells can occur midway through a multi-line row label. Removing
    # cells here is solely for label matching; source evidence stays untouched.
    text = re.sub(r"[\d,.，%％+()（）−\-]", "", _compact(row))
    # Deductions must precede the broader parent-profit rule.
    if ("归属" in text and "扣除" in text and "非经常性损益" in text
            and "净利润" in text):
        return "profit_deducted"
    if "经营活动产生的现金流量净额" in text:
        return "operating_cashflow"
    if any(label in text for label in (
        "归属于上市公司股东的净资产", "归属于挂牌公司股东的净资产",
        "归属于母公司所有者权益合计", "归属于母公司股东权益合计",
        "归属于母公司所有者权益", "归属于母公司股东的权益",
    )):
        return "equity_parent"
    if "归属" in text and "净利润" in text and "非经常性损益" not in text:
        return "profit_parent"
    if "营业收入" in text and "营业收入增长率" not in text:
        return "revenue"
    if re.search(r"(?:^|[、：:])总资产", text) or "资产总计" in text:
        return "total_assets"
    return None


def _report_year(pages: list[dict], filename: str) -> tuple[int | None, list[str]]:
    opening = _compact("\n".join(str(page.get("text", "")) for page in pages[:3]))
    title = re.search(r"(20\d{2})年(?:年度报告|度报告)", opening)
    file_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", filename)
    if title:
        year = int(title.group(1))
        warnings = []
        if file_match and int(file_match.group(1)) != year:
            warnings.append("文件名年份与年报标题不同，已采用年报标题年份，请核对报告。")
        return year, warnings
    if file_match:
        return int(file_match.group(1)), ["未识别年报标题年份，暂采用文件名年份，请人工核对。"]
    return None, ["未识别报告年度，请上传含完整封面的年度报告。"]


def _company(pages: list[dict]) -> str:
    for page in pages[:3]:
        for line in str(page.get("text", "")).splitlines():
            compact = _compact(line)
            match = re.search(
                r"([\u4e00-\u9fffA-Za-z（）()·]{3,55}(?:股份有限公司|有限责任公司|有限公司))",
                compact,
            )
            if match:
                name = match.group(1)
                for prefix in ("公司的中文名称", "公司中文名称", "中文名称", "公司名称"):
                    if name.startswith(prefix):
                        name = name[len(prefix):]
                if len(name) <= 50:
                    return name
    return "未识别公司"


def _currency(text: str, fallback: str = "unknown") -> str:
    matches = list(_CURRENCY.finditer(text))
    if matches:
        return "CNY" if matches[-1].group(1) == "人民币" else "unknown"
    if "人民币" in text:
        return "CNY"
    return fallback


def _table_context(lines: list[str], row_index: int, default_currency: str) -> tuple[str, str]:
    before = "\n".join(lines[max(0, row_index - 18):row_index + 1])
    matches = list(_UNIT.finditer(before))
    unit = matches[-1].group(1) if matches else "unknown"
    # Some reports place the unit immediately under the title, while a wrapped
    # row may be farther below. Do not borrow a unit from another PDF page.
    if unit == "unknown":
        all_matches = list(_UNIT.finditer("\n".join(lines)))
        unique = {match.group(1) for match in all_matches}
        if len(unique) == 1:
            unit = unique.pop()
    return unit, _currency(before, default_currency)


def _header(lines: list[str], row_index: int, report_year: int | None) -> dict | None:
    start = max(0, row_index - 18)
    best: tuple[int, list[int]] | None = None
    for index in range(start, row_index):
        line = lines[index]
        years = [int(match.group(1)) for match in _YEAR.finditer(line)]
        unique = list(dict.fromkeys(years))
        if len(unique) >= 2 and len(unique) <= 4:
            best = index, unique
    if best:
        index, years = best
        if report_year and report_year not in years:
            # Header years can occupy two physical text lines. Layout extraction
            # preserves their horizontal positions, so reconstruct column order.
            positioned = []
            for line in lines[index:min(row_index, index + 4)]:
                positioned.extend((match.start(), int(match.group(1)))
                                  for match in _YEAR.finditer(line))
            if any(year == report_year for _, year in positioned):
                years = list(dict.fromkeys(year for _, year in sorted(positioned)))
        context = "\n".join(lines[max(start, index - 2):row_index])
        restated = "调整前" in context and "调整后" in context
        return {"years": years, "text": context, "restated": restated,
                "growth": bool(re.search(r"(?:本期|本年|本报告期).*?(?:增|减)|增减[（(]%", _compact(context)))}
    # A short/continued statement sometimes uses date labels instead of years.
    context = _compact("\n".join(lines[max(start, row_index - 7):row_index]))
    if report_year and ("本报告期末" in context and "上年度末" in context
                        or "本期" in context and "上年同期" in context):
        return {"years": [report_year, report_year - 1], "text": context,
                "restated": "调整前" in context and "调整后" in context, "growth": True}
    return None


def _source_scope(lines: list[str], row_index: int, headline: bool) -> str:
    text = "\n".join(lines[:row_index + 1])
    headings = list(re.finditer(r"母公司(?:资产负债表|利润表|现金流量表)|合并(?:资产负债表|利润表|现金流量表)", text))
    if headings:
        return "parent" if headings[-1].group(0).startswith("母公司") else "consolidated"
    if headline:
        return "consolidated"
    return "unknown"


def _numbers(row: str) -> list[tuple[str, str | None]]:
    # Join line breaks only inside a printed thousands-separated number.
    source = re.sub(r"([,，])\s+(?=\d{3}(?:\D|$))", r"\1", row)
    source = re.sub(
        r"^\s*[\d一二三四五六七八九十]+[、.．]\s*(?=营业收入|归属于|经营活动|总资产|资产总计)",
        "", source,
    )
    values = []
    for match in _NUMBER.finditer(source):
        raw = match.group(0).strip()
        value = parse_decimal(raw)
        # Preserve missing and percentage cells as placeholders so a missing
        # current value never shifts the previous year's number into its slot.
        values.append((raw, value))
    return values


def _assign_year_values(values: list[tuple[str, str | None]], header: dict) -> list[tuple[int, str, str]]:
    years = header["years"]
    if not values or not years:
        return []
    # A blank cell with no dash, or a numeric footnote column, must not shift
    # values into a different year. Accept only a fully explained column count.
    expected = len(years) + int(header["growth"])
    if header["restated"]:
        expected = 1 + 2 * (len(years) - 1) + int(header["growth"])
    if len(values) != expected:
        return []
    if header["restated"]:
        # Current year is the first unambiguous column. Older columns contain
        # adjusted/unadjusted pairs: leave them for human entry rather than
        # silently claiming that either pair is the comparable value.
        return [(years[0], values[0][0], values[0][1])] if values[0][1] is not None else []
    count = len(values)
    indices = list(range(len(years)))
    if header["growth"] and count > len(years):
        # Standard Chinese annual headline table: current, prior, YoY, older.
        # Never assign the growth cell to the third reporting year.
        if len(years) >= 3:
            indices = [0, 1] + list(range(3, len(years) + 1))
    return [(year, values[index][0], values[index][1])
            for year, index in zip(years, indices) if index < count and values[index][1] is not None]


def _row_block(lines: list[str], start: int) -> tuple[str, int]:
    selected = [lines[start]]
    end = start + 1
    for index in range(start + 1, min(len(lines), start + 5)):
        line = lines[index]
        if _looks_like_row(line):
            break
        if re.search(r"主要财务指标|主要会计数据|每股收益|净资产收益率|年末.*年末", _compact(line)):
            break
        if _numbers("\n".join(selected)) and not line.strip():
            break
        # A wrapped label such as '的净利润' belongs to the row. A whole new
        # paragraph, unit/header or unrelated numbered row does not.
        if selected and _numbers("\n".join(selected)) and _metric_key("\n".join(selected)):
            compact = _compact(line)
            if compact and not ("净利润" in compact or "净资产" in compact
                                or "净额" in compact or "非经常性损益" in compact):
                break
        selected.append(line)
        end = index + 1
        if _metric_key("\n".join(selected)) and _numbers("\n".join(selected)):
            # Keep one more continuation only when the label is incomplete.
            compact = _compact("\n".join(selected))
            if not compact.endswith(("的", "扣除", "现金流量", "公司股东")):
                break
    return "\n".join(selected), end


def _missing(key: str, year: int, currency: str) -> dict[str, Any]:
    return {"key": key, "label": METRIC_LABELS[key], "year": year, "value": None,
            "raw_value": None, "unit": "unknown", "currency": currency, "page": None,
            "evidence": "", "status": "missing", "scope": "unknown",
            "extraction_note": "未可靠识别，请定位原文后人工补录。"}


def extract_text_pages(
    pages: list[dict], filename: str, *, sha256: str = "", source_url: str = "",
) -> dict[str, Any]:
    """Extract review candidates from one-based page text (also useful in tests)."""
    normalized_pages = [{"number": int(page.get("number", index + 1)),
                         "text": str(page.get("text", ""))}
                        for index, page in enumerate(pages)]
    if not normalized_pages:
        raise ValueError("PDF 没有可读取页面，请重新导出完整年报。")
    cover = _compact(normalized_pages[0]["text"])
    if re.search(r"半年度报告|季度报告|季报", cover) and not re.search(
        r"20\d{2}年(?:年度报告|度报告)", cover,
    ):
        raise ValueError("当前仅支持年度报告，请勿将半年报或季报与年报直接对比。")
    text_length = sum(len(re.sub(r"\s", "", page["text"])) for page in normalized_pages)
    if text_length < 60 or (len(normalized_pages) > 5 and text_length / len(normalized_pages) < 80):
        raise ValueError("未提取到足够文字，可能是扫描件。请先做 OCR，或上传可复制文字的 PDF。")
    report_year, warnings = _report_year(normalized_pages, filename)
    if re.search(r"20\d{2}年(?:年度报告|度报告)摘要", cover):
        warnings.append("这是年度报告摘要，资料问答仅覆盖已上传的摘要内容。")
    company = _company(normalized_pages)
    if company == "未识别公司":
        warnings.append("未可靠识别公司名称，请核对封面；不同公司不能直接进行同比对比。")
    opening_text = "\n".join(page["text"] for page in normalized_pages[:20])
    currency = _currency(opening_text)
    candidates: dict[tuple[str, int], tuple[int, dict]] = {}
    restated_pages: set[int] = set()
    ambiguous: set[tuple[str, int]] = set()
    for page in normalized_pages:
        lines = page["text"].splitlines()
        page_number = page["number"]
        page_text = _compact(page["text"])
        headline = "主要会计数据" in page_text
        # A following page may continue the headline table. It remains a review
        # candidate and needs its own year header to be assigned correctly.
        index = 0
        while index < len(lines):
            if not _looks_like_row(lines[index]):
                index += 1
                continue
            row, next_index = _row_block(lines, index)
            key = _metric_key(row)
            if key is None:
                index += 1
                continue
            scope = _source_scope(lines, index, headline)
            if scope == "parent":
                index = max(index + 1, next_index)
                continue
            header = _header(lines, index, report_year)
            values = _numbers(row)
            if not header or not values:
                index = max(index + 1, next_index)
                continue
            if report_year and report_year not in header["years"]:
                index = max(index + 1, next_index)
                continue
            if header["restated"]:
                restated_pages.add(page_number)
            unit, row_currency = _table_context(lines, index, currency)
            priority = (100 if headline else 70 if scope == "consolidated" else 20)
            if page_number > 25 and headline:
                priority = 60
            for year, raw, value in _assign_year_values(values, header):
                if report_year and (year > report_year or year < report_year - 2):
                    continue
                record = {"key": key, "label": METRIC_LABELS[key], "year": year,
                          "value": value, "raw_value": raw, "unit": unit,
                          "currency": row_currency, "page": page_number,
                          "evidence": row[:800], "status": "candidate", "scope": scope,
                          "header": header["text"][-600:],
                          "extraction_note": "自动提取候选，请对照原文核对年份、单位和口径后确认。"}
                if header["restated"]:
                    record["extraction_note"] += " 同表有调整前/后列，仅自动提取当年明确列。"
                identity = key, year
                existing = candidates.get(identity)
                if existing is None or priority > existing[0]:
                    candidates[identity] = priority, record
                    ambiguous.discard(identity)
                elif priority == existing[0] and (
                    value, unit, row_currency
                ) != (existing[1]["value"], existing[1]["unit"], existing[1]["currency"]):
                    ambiguous.add(identity)
            index = max(index + 1, next_index)
    for page_number in sorted(restated_pages):
        warnings.append(f"PDF 第 {page_number} 页存在调整前/后列，历史年度未自动选列，请人工核对可比口径。")
    for key, year in sorted(ambiguous):
        warnings.append(f"{year} 年{METRIC_LABELS[key]}存在同优先级冲突，已保留来源并要求人工补录。")
        record = candidates[(key, year)][1]
        record.update(value=None, raw_value=None, status="missing",
                      extraction_note="多处数据冲突，请核对合并口径后人工补录。")
    if report_year is not None:
        for key in METRIC_LABELS:
            for year in (report_year, report_year - 1):
                candidates.setdefault((key, year), (0, _missing(key, year, currency)))
    records = [item[1] for item in candidates.values()]
    records.sort(key=lambda item: (list(METRIC_LABELS).index(item["key"]), -item["year"]))
    present = sum(record["status"] == "candidate" and record["year"] == report_year
                  for record in records)
    if present < len(METRIC_LABELS):
        warnings.append(f"当年六项指标可靠候选识别 {present}/6；缺失项不会作为零值参与计算。")
    if any(record["unit"] == "unknown" for record in records if record["status"] == "candidate"):
        warnings.append("部分候选未识别金额单位，请对照原文确认，系统不会自行假定单位。")
    if currency == "unknown":
        warnings.append("未可靠识别人民币口径，请核对币种后确认。")
    digest = sha256 or hashlib.sha256(
        "\n".join(page["text"] for page in normalized_pages).encode("utf-8")
    ).hexdigest()
    return {"id": digest[:20], "filename": Path(filename).name, "company": company,
            "year": report_year, "currency": currency, "page_count": len(normalized_pages),
            "pages": normalized_pages, "metrics": records, "warnings": list(dict.fromkeys(warnings)),
            "source_url": source_url, "sha256": digest}


def extract_report(path: Path, filename: str | None = None, source_url: str = "") -> dict:
    """Read a user-selected PDF locally. No model or network access occurs."""
    from pypdf import PdfReader

    path = Path(path)
    if not path.is_file():
        raise ValueError("未找到上传的 PDF 文件，请重新上传。")
    size = path.stat().st_size
    if size == 0 or size > MAX_FILE_BYTES:
        raise ValueError("请上传非空且不超过 25 MB 的 PDF。")
    with path.open("rb") as handle:
        signature = handle.read(1024)
    if b"%PDF-" not in signature:
        raise ValueError("文件不是有效 PDF，请上传原始年报 PDF。")
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF 已加密，请先解密后再上传。")
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise ValueError("仅支持 1 至 500 页的 PDF，请拆分超长报告后上传。")
        pages = []
        for index, page in enumerate(reader.pages):
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except (TypeError, NotImplementedError):
                text = page.extract_text() or ""
            if len(text) > 500_000:
                raise ValueError("单页文字量异常，请重新导出 PDF 后上传。")
            pages.append({"number": index + 1, "text": text})
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF 无法解析，可能已损坏或受密码保护，请重新导出后上传。") from error
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return extract_text_pages(pages, filename or path.name, sha256=digest, source_url=source_url)
