"""Deterministic financial comparison and evidence retrieval.

Amounts keep their original unit in the source record. Only explicitly reviewed
RMB consolidated figures are normalized and used in calculations. No model,
network request, file read, or executable tool is used by this module.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


METRICS: tuple[tuple[str, str], ...] = (
    ("revenue", "营业收入"),
    ("profit_parent", "归母净利润"),
    ("profit_deducted", "扣非归母净利润"),
    ("operating_cashflow", "经营现金流净额"),
    ("total_assets", "总资产"),
    ("equity_parent", "归母净资产"),
)
UNIT_FACTORS = {
    "元": Decimal("1"),
    "千元": Decimal("1000"),
    "万元": Decimal("10000"),
    "百万元": Decimal("1000000"),
    "亿元": Decimal("100000000"),
}
_ALIASES = {
    "revenue": ("营业收入", "营收"),
    "profit_parent": (
        "归母净利润", "归母净利", "归属于上市公司股东的净利润", "归属于母公司股东的净利润",
        "归属于母公司所有者的净利润",
    ),
    "profit_deducted": ("扣非", "扣除非经常性损益"),
    "operating_cashflow": ("经营现金流", "经营活动产生的现金流量净额", "现金流", "经营活动现金"),
    "total_assets": ("总资产", "资产总额", "资产规模"),
    "equity_parent": (
        "归母净资产", "归母所有者权益", "归属于上市公司股东的净资产", "归属于母公司股东的净资产",
        "归属于上市公司股东的所有者权益", "归属于母公司股东的所有者权益",
        "归属于母公司所有者的权益", "归属于母公司的所有者权益", "归属于母公司所有者权益", "净资产",
    ),
}
_TOTAL_REVENUE = re.compile(r"营业总收入|总营收|总收入|收入总额")
_TOTAL_PROFIT = re.compile(
    r"(?:合并|整体|总)(?:口径)?(?:的)?净利润|净利润(?:合计|总额)|利润总额|"
    r"(?:含|包括)少数股东损益(?:的)?净利润"
)
_PARENT_EQUITY = re.compile(
    r"归母(?:净资产|所有者权益|权益)|"
    r"归属于(?:上市公司|母公司)(?:股东|所有者)?的?(?:净资产|所有者权益|权益)"
)
_TOTAL_EQUITY = re.compile(
    r"所有者权益|股东权益合计|权益合计|净资产总额|合并净资产|少数股东权益|全部净资产"
)
_DEDUCTED_PROFIT = re.compile(
    r"(?:归母|归属于(?:上市公司|母公司)(?:股东|所有者)?的?)?"
    r"(?:扣非|扣除非经常性损益)(?:口径(?:下)?|之后|以后|后)?的?"
    r"(?:归母|归属于(?:上市公司|母公司)(?:股东|所有者)?的?)?(?:净利润|净利|利润)?"
)
_POST_DEDUCTED_PROFIT = re.compile(
    r"(?:归母|归属于(?:上市公司|母公司)(?:股东|所有者)?的?)?(?:净利润|净利)"
    r"(?:扣非|扣除非经常性损益)(?:之后|以后|后)?"
)
_NON_OPERATING_CASHFLOW = re.compile(
    r"(?:投资|筹资|融资)(?:活动)?(?:产生的|的)?(?:净)?现金流(?:量)?"
)
_OPERATING_CASHFLOW = re.compile(r"经营(?:活动)?(?:产生的)?(?:净)?现金流(?:量)?(?:净额)?")
_NON_ANNUAL_PERIOD = re.compile(
    r"季度|季报|半年度|半年报|半年|月度|月报|每月|单月|各月|月均|[Qq][1-4]|[Hh][12]|"
    r"(?<!\d)(?:\d{1,2}|[一二三四五六七八九十]{1,3})月(?:份)?(?:底|末)?(?:的)?"
    r"(?:营收|营业收入|收入|净利润|归母|利润|现金流|经营现金|总资产|净资产|资产|权益|业绩|财务数据|数据|同比)|"
    r"(?<!\d)\d{1,2}(?:-|至|到)\d{1,2}月"
)
_SEGMENT_SCOPE = re.compile(
    r"分产品|分地区|分行业|分业务|分部|分渠道|按(?:产品|地区|行业|业务|渠道)|"
    r"产品(?:类别|线|维度|口径)|地区(?:维度|口径)|直销|批发|经销|国外|国内|境外|境内|海外"
)
_ATTRIBUTABLE_PREFIX = re.compile(r"归属于(?:上市公司|母公司)(?:股东|所有者)?的?")
_SINGLE_ENTITY_SCOPE = re.compile(r"母公司|单体|单独报表|个别报表|非合并(?:口径|报表)?")
_STOP_WORDS = {
    "公司", "年报", "报告", "这个", "什么", "如何", "分析", "请问", "根据", "详细", "变化",
    "情况", "原因", "以及", "为什么", "是否", "哪些", "本年", "今年", "多少", "一下", "请帮",
    "帮我", "最近", "年度", "同比", "增长", "下降", "解释", "一下", "里面", "数据", "资料",
}
_DOMAIN_TERMS = (
    "营业收入", "营业总收入", "合并净利润", "利润总额", "所有者权益", "少数股东权益",
    "归母净利润", "扣非净利润", "现金流", "净利润", "分红", "风险", "产能", "销售", "成本", "存货", "研发",
    "审计意见", "诉讼", "关联交易", "毛利", "应收账款", "市场", "信用", "减值", "负债",
    "偿债", "流动", "利润", "主要会计数据", "非经常性损益", "会计政策", "重述", "调整后",
    "投资活动产生的现金流量净额", "筹资活动产生的现金流量净额", "季度", "半年度", "月度",
    "分产品", "分地区", "直销", "批发", "境内", "境外", "国内", "国外", "母公司", "单体",
)


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("，", "").replace("−", "-")
    if text.startswith(("(", "（")) and text.endswith((")", "）")):
        text = "-" + text[1:-1]
    if not re.fullmatch(r"[+-]?(?:\d{1,30}(?:\.\d{1,12})?|\.\d{1,12})", text):
        return None
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _currency(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"CNY", "RMB", "人民币", "人民币元"}:
        return "CNY"
    if text in {"", "UNKNOWN", "未知", "NONE", "NULL"}:
        return None
    return text


def _company_name(value: Any) -> str:
    name = re.sub(r"\s+", "", str(value or "")).replace("（", "(").replace("）", ")").lower()
    if name in {"未识别公司", "未知公司", "待确认公司", "未识别", "未知", "unknown", "none", "null"}:
        return ""
    return name


def _year(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if 1900 <= result <= 2200 else None


def _record(report: dict, metric: dict) -> dict:
    result = dict(metric)
    result["report_id"] = report.get("id", "")
    result["filename"] = report.get("filename", "")
    result["label"] = dict(METRICS).get(result.get("key"), result.get("label", ""))
    result["year"] = _year(result.get("year"))
    return result


def _source_candidates(reports: list[dict], key: str, year: int) -> list[dict]:
    return [
        _record(report, metric)
        for report in reports
        for metric in report.get("metrics", [])
        if metric.get("key") == key and _year(metric.get("year")) == year
    ]


def _unreviewed_yuan(metric: dict | None) -> Decimal | None:
    if not metric or _currency(metric.get("currency")) != "CNY":
        return None
    factor = UNIT_FACTORS.get(metric.get("unit"))
    number = _number(metric.get("value"))
    if factor is None or number is None:
        return None
    with localcontext() as context:
        context.prec = 40
        return number * factor


def _reviewed_amount(metric: dict | None, period: str) -> tuple[Decimal | None, list[str]]:
    if not metric or metric.get("value") is None:
        return None, [f"{period}缺少可核对的数值。"]
    notes: list[str] = []
    if metric.get("status") != "confirmed":
        notes.append(f"{period}为自动提取候选，需核对原文并确认。")
    if metric.get("scope") != "consolidated":
        notes.append(f"{period}合并报表口径未确认，暂不用于比较。")
    if _currency(metric.get("currency")) != "CNY":
        notes.append(f"{period}人民币币种未确认，暂不用于比较。")
    if metric.get("unit") not in UNIT_FACTORS:
        notes.append(f"{period}金额单位未识别，请核对原文。")
    if _number(metric.get("value")) is None:
        notes.append(f"{period}数值无效，请核对原文。")
    page = metric.get("page")
    if (
        not isinstance(page, int) or isinstance(page, bool) or page < 1
        or not str(metric.get("evidence", "")).strip()
    ):
        notes.append(f"{period}缺少来源页码或原文证据。")
    if notes:
        return None, notes
    return _unreviewed_yuan(metric), []


def _choose_candidate(candidates: list[dict], period: str) -> tuple[dict | None, list[str], bool]:
    if not candidates:
        return None, [], False
    chosen = candidates[0]
    notes: list[str] = []
    ambiguous = False
    same_report = [item for item in candidates if item["report_id"] == chosen["report_id"]]
    # Equal repeated rows are harmless. Different values in the same document
    # need an explicit extraction/review decision, not an arbitrary first match.
    values = {_unreviewed_yuan(item) for item in same_report}
    values.discard(None)
    if len(values) > 1:
        ambiguous = True
        notes.append(f"{period}在同一报告中有多个不同候选，需先消除提取歧义。")
    chosen_value = _unreviewed_yuan(chosen)
    for other in candidates[1:]:
        other_value = _unreviewed_yuan(other)
        if (
            other["report_id"] != chosen["report_id"]
            and chosen_value is not None
            and other_value is not None
            and chosen_value != other_value
        ):
            notes.append(
                f"{period}在不同报告中披露或提取的数值不同；优先使用较新年报的可比期，"
                "请核对是否存在调整、重述或提取差异。"
            )
            break
    return chosen, notes, ambiguous


def build_comparison(reports: list[dict]) -> dict:
    """Compare consecutive consolidated RMB periods with explicit review gates."""
    if not reports:
        return {
            "company": "", "current_year": None, "previous_year": None,
            "rows": [], "insights": [], "warnings": ["请先上传中文上市公司年度报告。"],
            "coverage": {"total": 6, "ready": 0, "needs_review": 0, "missing": 6,
                         "confirmed_values": 0, "total_values": 12, "evidence_values": 0,
                         "confirmed_rows": 0, "confirmed_total": 12},
        }
    if len(reports) > 2:
        raise ValueError("一次最多比较两份年报，请移除多余文件。")
    years = [_year(report.get("year")) for report in reports]
    if any(year is None for year in years):
        raise ValueError("有报告未识别出报告年度。请使用包含封面和主要会计数据的完整年度报告。")
    if len(set(years)) != len(years):
        raise ValueError("两份文件的报告年度相同。请保留一份，或上传同一公司相邻两年的年报。")
    ordered = sorted(reports, key=lambda report: int(report["year"]), reverse=True)
    if len(ordered) == 2 and int(ordered[0]["year"]) - int(ordered[1]["year"]) != 1:
        raise ValueError("请选择同一公司相邻两年的年度报告，避免把跨年差额当作同比。")
    known_names = {_company_name(report.get("company")) for report in ordered}
    known_names.discard("")
    if len(known_names) > 1:
        raise ValueError("两份报告的公司名称不同。请上传同一公司的相邻年度报告。")
    known_currencies = {_currency(report.get("currency")) for report in ordered}
    known_currencies.discard(None)
    if len(known_currencies) > 1 or (known_currencies and known_currencies != {"CNY"}):
        raise ValueError("报告币种不兼容。当前版本仅支持人民币年报，不自动进行汇率换算。")

    current_year = int(ordered[0]["year"])
    previous_year = current_year - 1
    warnings: list[str] = []
    company = str(ordered[0].get("company") or "未识别公司")
    identity_uncertain = any(not _company_name(report.get("company")) for report in ordered)
    if identity_uncertain:
        warnings.append("有报告未识别公司名称，尚不能确认两期属于同一主体，暂不计算同比。")
    if None in {_currency(report.get("currency")) for report in ordered}:
        warnings.append("有报告未识别总体币种；每个指标仍需明确为人民币后才能计算。")

    rows: list[dict] = []
    for key, label in METRICS:
        current, current_notes, current_ambiguous = _choose_candidate(
            _source_candidates(ordered, key, current_year), "本期"
        )
        previous, previous_notes, previous_ambiguous = _choose_candidate(
            _source_candidates(ordered, key, previous_year), "上期"
        )
        current_yuan, current_issues = _reviewed_amount(current, "本期")
        previous_yuan, previous_issues = _reviewed_amount(previous, "上期")
        notes = current_notes + previous_notes + current_issues + previous_issues
        if current and previous and current["report_id"] != previous["report_id"]:
            notes.append("两期数据来自不同报告，请额外检查会计政策和调整口径是否一致。")
        if identity_uncertain or current_ambiguous:
            current_yuan = None
        if identity_uncertain or previous_ambiguous:
            previous_yuan = None
        ready = current_yuan is not None and previous_yuan is not None
        change_pct: str | None = None
        delta_yuan: str | None = None
        if ready:
            with localcontext() as context:
                context.prec = 40
                delta_yuan = _decimal_text(current_yuan - previous_yuan)
                if previous_yuan > 0:
                    change_pct = format(
                        ((current_yuan - previous_yuan) / previous_yuan * 100)
                        .quantize(Decimal("0.01")), "f"
                    )
                else:
                    notes.append("上期基数为零或负数，同比增长率不适用；请查看金额变化。")
        status = "ready" if ready else "needs_review"
        if not current or not previous or current.get("value") is None or previous.get("value") is None:
            status = "missing"
        row = {
            "key": key, "label": label, "current": current, "previous": previous,
            "current_yuan": _decimal_text(current_yuan) if current_yuan is not None else None,
            "previous_yuan": _decimal_text(previous_yuan) if previous_yuan is not None else None,
            "change_pct": change_pct, "delta_yuan": delta_yuan, "status": status,
            "notes": list(dict.fromkeys(notes)),
        }
        rows.append(row)
        for note in current_notes + previous_notes:
            warnings.append(f"{label}：{note}")

    ready_count = sum(row["status"] == "ready" for row in rows)
    confirmed_values = sum(
        metric is not None and metric.get("status") == "confirmed"
        for row in rows for metric in (row["current"], row["previous"])
    )
    evidence_values = sum(
        metric is not None and metric.get("value") is not None
        for row in rows for metric in (row["current"], row["previous"])
    )
    if ready_count < len(METRICS):
        warnings.append("待核对或缺失数据不参与正式同比计算，不能用零代替。")
    return {
        "company": company, "current_year": current_year, "previous_year": previous_year,
        "rows": rows, "insights": _insights(rows, current_year),
        "warnings": list(dict.fromkeys(warnings)),
        "coverage": {
            "total": len(METRICS), "ready": ready_count,
            "needs_review": sum(row["status"] == "needs_review" for row in rows),
            "missing": sum(row["status"] == "missing" for row in rows),
            "confirmed_values": confirmed_values, "total_values": len(METRICS) * 2,
            "evidence_values": evidence_values, "confirmed_rows": ready_count,
            "confirmed_total": len(METRICS) * 2,
        },
    }


def _insights(rows: list[dict], year: int) -> list[str]:
    result: list[str] = []
    by_key = {row["key"]: row for row in rows}
    for key in ("revenue", "profit_parent", "operating_cashflow"):
        row = by_key[key]
        if row["status"] == "ready" and row["change_pct"] is not None:
            change = Decimal(row["change_pct"])
            movement = "增长" if change > 0 else "下降" if change < 0 else "持平"
            text = f"{year} 年{row['label']}同比{movement}"
            result.append(text + (f" {abs(change):.2f}%。" if change else "。"))
    cash = by_key["operating_cashflow"]["current_yuan"]
    profit = by_key["profit_parent"]["current_yuan"]
    if cash is not None and profit is not None and Decimal(profit) > 0:
        with localcontext() as context:
            context.prec = 40
            ratio = Decimal(cash) / Decimal(profit)
            result.append(
                f"{year} 年经营现金流净额 / 归母净利润为 {ratio:.2f} 倍。"
                "两个指标口径不同，该比例仅用于观察，不能单独判断盈利质量。"
            )
    if not result:
        result.append("请先核对并确认关键数据；确认后的可比指标会在此生成事实观察。")
    return result


def _citation(metric: dict) -> dict:
    return {
        "report_id": metric.get("report_id", ""), "filename": metric.get("filename", ""),
        "page": metric.get("page"), "evidence": str(metric.get("evidence", "")),
    }


def _unique_citations(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple] = set()
    for item in items:
        signature = (item.get("report_id"), item.get("page"), item.get("evidence"))
        if signature not in seen and item.get("page") and item.get("evidence"):
            seen.add(signature)
            result.append(item)
    return result


def _metric_keys(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", question)
    without_deducted = _POST_DEDUCTED_PROFIT.sub("", compact)
    without_deducted = _DEDUCTED_PROFIT.sub("", without_deducted)
    selected = [
        key for key, aliases in _ALIASES.items()
        if any(alias in (without_deducted if key == "profit_parent" else compact) for alias in aliases)
    ]
    # "净利润" is ambiguous. We can show the application's explicitly labelled
    # attributable-profit field, but never let a deducted-profit modifier also
    # trigger this generic fallback.
    if "净利润" in without_deducted and "profit_parent" not in selected:
        multiple_profit_request = bool(re.search(r"和|与|及|对比|比较|区别|分别|[、；;？?]", without_deducted))
        if "profit_deducted" not in selected or multiple_profit_request:
            selected.append("profit_parent")
    selected.sort(key=lambda key: [item[0] for item in METRICS].index(key))
    return selected


def _scope_limitations(question: str) -> list[str]:
    """Do not silently substitute a narrower structured accounting concept."""
    compact = re.sub(r"\s+", "", question)
    notes = []
    if _NON_ANNUAL_PERIOD.search(compact):
        notes.append(
            "当前结构化数据采用年度主要会计数据口径；季度、半年度或月度需要核对对应期间，"
            "不能用全年数值代答。"
        )
    if _SEGMENT_SCOPE.search(compact):
        notes.append(
            "当前结构化指标采用全公司合并口径；分产品、分地区或分渠道需要核对分部披露，"
            "不能用公司总数代答。"
        )
    # Attributable-to-parent profit/equity is still a consolidated-report concept;
    # its legal wording must not be mistaken for a parent-only statement request.
    if _SINGLE_ENTITY_SCOPE.search(_ATTRIBUTABLE_PREFIX.sub("", compact)):
        notes.append(
            "当前结构化比较使用合并口径；母公司或单体报表需要单独核对，不能用合并数值代答。"
        )
    if _NON_OPERATING_CASHFLOW.search(compact):
        notes.append(
            "当前结构化现金流指标是经营活动产生的现金流量净额；投资或筹资活动是不同口径，"
            "不能用经营现金流数值代答。"
        )
    if _TOTAL_REVENUE.search(compact):
        notes.append(
            "当前结构化指标是营业收入，营业总收入可能还包含其他收入口径，"
            "不能用营业收入数值代替你所问的总口径。"
        )
    if _TOTAL_PROFIT.search(compact):
        notes.append(
            "当前结构化利润指标是归属于上市公司股东的净利润及扣非归母净利润；"
            "合并净利润、利润总额等是不同口径，不能用归母数值代答。"
        )
    without_parent_equity = _PARENT_EQUITY.sub("", compact)
    if _TOTAL_EQUITY.search(without_parent_equity):
        notes.append(
            "当前结构化权益指标是归属于上市公司股东的净资产；"
            "所有者权益合计可能包含少数股东权益，不能用归母净资产数值代替总权益。"
        )
    return notes


def _display_metric(metric: dict) -> str:
    number = _number(metric.get("value"))
    text = f"{number:,.2f}" if number is not None else "未识别"
    state = "已核对" if metric.get("status") == "confirmed" else "待核对候选"
    currency = "人民币" if _currency(metric.get("currency")) == "CNY" else "币种待确认"
    return (
        f"{metric.get('year')} 年：{text} {metric.get('unit', '单位待确认')}（{currency}，{state}；"
        f"《{metric.get('filename', '')}》PDF 第 {metric.get('page')} 页）"
    )


def _retrieval_terms(question: str) -> list[str]:
    terms = [term for term in _DOMAIN_TERMS if term in question]
    # Broader financial synonyms stay on the retrieval path; canonical search
    # terms improve source finding without mapping them to a narrower metric.
    if _TOTAL_REVENUE.search(question):
        terms.append("营业总收入")
    if _TOTAL_EQUITY.search(_PARENT_EQUITY.sub("", question)):
        terms.append("所有者权益")
    if not _TOTAL_REVENUE.search(question) and any(alias in question for alias in _ALIASES["revenue"]):
        terms.append("营业收入")
    terms.extend(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", question))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", question):
        terms.extend(chunk[index:index + 2] for index in range(len(chunk) - 1))
    return list(dict.fromkeys(term for term in terms if term not in _STOP_WORDS))


def _retrieve(reports: list[dict], question: str, limit: int = 3) -> list[dict]:
    terms = _retrieval_terms(question)
    if not terms:
        return []
    matches: list[tuple[float, int, dict]] = []
    for report in reports:
        for page in report.get("pages", []):
            text = str(page.get("text", ""))
            page_number = page.get("number")
            if not text.strip() or not isinstance(page_number, int) or page_number < 1:
                continue
            lowered = text.lower()
            hits = [(term, lowered.find(term.lower())) for term in terms]
            hits = [(term, position) for term, position in hits if position >= 0]
            if not hits:
                continue
            score = sum((3 if term in _DOMAIN_TERMS else 1) for term, _ in hits)
            # A long table-of-contents page should not dominate a real paragraph
            # merely by containing many one-off chapter titles.
            if "目录" in text[:160]:
                score *= 0.35
            anchor = max(hits, key=lambda item: (len(item[0]), -item[1]))[1]
            start = max(0, anchor - 90)
            end = min(len(text), anchor + 510)
            snippet = text[start:end].strip()
            matches.append((score, int(report.get("year") or 0), {
                "report_id": report.get("id", ""), "filename": report.get("filename", ""),
                "page": page_number, "evidence": snippet,
            }))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return _unique_citations([item[2] for item in matches])[:limit]


def answer_question(reports: list[dict], question: str) -> dict:
    """Answer supported questions locally; return source snippets for other ones."""
    question = str(question or "").strip()[:2000]
    base: dict = {"mode": "local", "needs_model": False, "citations": []}
    if not question:
        return {**base, "answer": "请输入问题，例如“营业收入同比变化多少”或“有哪些风险提示”。"}
    if re.search(r"怎么用|如何使用|怎么使用|能做什么|使用方法|使用说明|你是谁", question) or (
        question.strip(" ，。！？!?,.").lower() in {"你好", "您好", "hi", "hello"}
    ):
        return {**base, "answer": (
            "我是年报分析助手。先上传同一公司相邻年度的中文年报，或载入公开演示资料；"
            "点击指标查看原文页，核对金额、单位和口径后确认。确认的数据可进行同比计算，"
            "你也可以提问、查找原文并导出核对底稿。默认本地处理；可选的 DeepSeek 解读"
            "需要先预览发送内容并明确同意。"
        )}
    if re.search(
        r"隐私|泄露|泄漏|上传到|发给(?:模型|云端|服务器|DeepSeek)|外发|本地处理|联网|数据安全",
        question, re.IGNORECASE,
    ):
        return {**base, "answer": (
            "PDF 提取、指标核对、金额计算和本地检索在本机完成。资料会保存在本地工作区，"
            "可从资料列表删除。只有在你打开 DeepSeek 发送预览并明确确认后，预览中的内容"
            "才会发送给该模型服务；本地处理不代表已完成加密或企业级数据防泄漏。"
        )}
    if not reports:
        return {**base, "answer": "请先上传年报或载入公开演示资料，再针对资料提问。"}
    if re.search(r"买入|卖出|值得买|荐股|目标价|投资建议", question):
        return {**base, "answer": (
            "这个助手用于年报证据核对和财务信息整理，不根据两期指标生成买卖结论。"
            "你可以问营业收入、归母净利润、经营现金流的变化，或检索年报里的风险披露。"
        )}

    selected_keys = _metric_keys(question)
    scope_limitations = _scope_limitations(question)
    causal = bool(re.search(r"为什么|原因|为何|驱动|导致|解释.*变化", question))
    if selected_keys and not causal and not scope_limitations:
        try:
            comparison = build_comparison(reports)
        except ValueError as error:
            return {**base, "answer": str(error)}
        selected_rows = [row for row in comparison["rows"] if row["key"] in selected_keys]
        requested_years = {int(year) for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", question)}
        wants_growth = bool(re.search(r"同比|增长|下降|变化|增减|对比|比较", question))
        supported_growth_period = not requested_years or (
            comparison["current_year"] in requested_years
            and requested_years <= {comparison["current_year"], comparison["previous_year"]}
        )
        ordered = sorted(reports, key=lambda source: int(source["year"]), reverse=True)
        lines: list[str] = []
        compact = re.sub(r"\s+", "", question)
        if "profit_parent" in selected_keys and not any(alias in compact for alias in _ALIASES["profit_parent"]):
            lines.append(
                "口径说明：这里将泛称“净利润”按当前结构化字段“归属于上市公司股东的净利润”"
                "（归母净利润）展示，不等同于包含少数股东损益的合并净利润。\n"
            )
        if "equity_parent" in selected_keys and not _PARENT_EQUITY.search(compact):
            lines.append(
                "口径说明：这里的净资产指归属于上市公司股东的净资产（归母净资产），"
                "不作为所有者权益合计展示。\n"
            )
        if "operating_cashflow" in selected_keys and not _OPERATING_CASHFLOW.search(compact):
            lines.append(
                "口径说明：这里将泛称“现金流”按当前结构化字段“经营活动产生的现金流量净额”展示，"
                "不代表投资、筹资活动现金流或现金净增加额。\n"
            )
        citations: list[dict] = []
        for row in selected_rows:
            lines.append(row["label"] + "：")
            if requested_years:
                relevant = []
                for target_year in sorted(requested_years, reverse=True):
                    metric, _, _ = _choose_candidate(
                        _source_candidates(ordered, row["key"], target_year), "所问年度"
                    )
                    if metric:
                        relevant.append(metric)
            else:
                relevant = [metric for metric in (row["current"], row["previous"]) if metric]
            if not relevant:
                lines.append("没有找到所问年度的可核对数据，未用零代替。")
            for metric in relevant:
                lines.append(_display_metric(metric))
                citations.append(_citation(metric))
            if wants_growth:
                if not supported_growth_period:
                    lines.append(
                        f"当前底稿的同比区间为 {comparison['current_year']} / "
                        f"{comparison['previous_year']}，不能把它作为所问年度的同比。"
                    )
                elif row["status"] == "ready" and row["change_pct"] is not None:
                    change = Decimal(row["change_pct"])
                    movement = "增长" if change > 0 else "下降" if change < 0 else "持平"
                    lines.append(
                        f"{comparison['current_year']} 年相对 {comparison['previous_year']} 年同比"
                        + (f"{movement} {abs(change):.2f}%。" if change else "持平。")
                    )
                    # The result depends on both periods even when the user
                    # explicitly mentions only one year.
                    citations.extend(_citation(metric) for metric in (row["current"], row["previous"]))
                elif row["status"] == "ready":
                    lines.append("上期基数为零或负数，同比增长率不适用。")
                    lines.append(f"金额变化为 {Decimal(row['delta_yuan']):,.2f} 元。")
                else:
                    lines.append("两期数据尚未全部核对且满足可比条件，暂不计算同比。")
            lines.append("")
        if (
            "operating_cashflow" in selected_keys and "profit_parent" in selected_keys
            and (not requested_years or requested_years == {comparison["current_year"]})
        ):
            cash_row = next(row for row in comparison["rows"] if row["key"] == "operating_cashflow")
            profit_row = next(row for row in comparison["rows"] if row["key"] == "profit_parent")
            cash, profit = cash_row["current_yuan"], profit_row["current_yuan"]
            if cash is not None and profit is not None and Decimal(profit) > 0:
                with localcontext() as context:
                    context.prec = 40
                    ratio = Decimal(cash) / Decimal(profit)
                    lines.append(
                        f"本期经营现金流净额 / 归母净利润为 {ratio:.2f} 倍。"
                        "两者口径不同，比例仅供观察，不能单独用于判断盈利质量。"
                    )
        return {**base, "answer": "\n".join(lines).strip(), "citations": _unique_citations(citations)}

    citations = _retrieve(reports, question)
    if not citations:
        return {**base, "answer": (
            ("\n".join(scope_limitations) + "\n" if scope_limitations else "")
            +
            "在当前资料中没有检索到足够的相关证据，暂不能回答这个问题。"
            "请补充资料，或使用年报里的具体指标、章节名和关键词提问。"
        )}
    lead = ("\n".join(scope_limitations) + "\n以下仅检索原文，不以结构化的较窄指标代答。\n" if scope_limitations else "") + (
        "仅凭指标变化不能确定经营原因。下面是检索到的相关原文，请先核对；"
        "其中内容是否足以支持原因解释，还需要结合完整章节判断。"
        if causal else "检索到以下相关原文，供你核对。以下是原文片段，尚未形成独立分析结论。"
    )
    excerpts = [lead]
    for index, source in enumerate(citations, 1):
        excerpts.append(
            f"[{index}] 《{source['filename']}》PDF 第 {source['page']} 页\n{source['evidence']}"
        )
    return {**base, "answer": "\n\n".join(excerpts), "citations": citations, "needs_model": True}


def _md(value: Any) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    ).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _memo_value(metric: dict | None) -> str:
    if not metric or metric.get("value") is None:
        return "缺失"
    value = _number(metric.get("value"))
    amount = f"{value:,.2f}" if value is not None else "无效数值"
    state = "已核对" if metric.get("status") == "confirmed" else "待核对候选"
    return f"{amount} {_md(metric.get('unit'))}；{state}"


def render_markdown(comparison: dict, reports: list[dict], ai_text: str = "") -> str:
    """Export a reviewable memo, preserving original evidence and review status."""
    company = _md(comparison.get("company") or "待确认公司")
    current_year, previous_year = comparison.get("current_year"), comparison.get("previous_year")
    coverage = comparison.get("coverage", {})
    lines = [
        f"# {company} 年报核对底稿", "",
        f"比较年度：{current_year or '待识别'} / {previous_year or '待识别'}。",
        "用途：财务信息整理和人工核对。候选值不参与正式计算，缺失值不以零代替。", "",
        f"可计算指标：{coverage.get('ready', 0)} / {coverage.get('total', 6)}；"
        f"已确认数据：{coverage.get('confirmed_values', 0)} / {coverage.get('total_values', 12)}。", "",
        "## 指标对比", "",
        f"| 指标 | {current_year or '本期'}原始金额 | {previous_year or '上期'}原始金额 | 同比 | 状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in comparison.get("rows", []):
        pct = f"{row['change_pct']}%" if row.get("change_pct") is not None else "暂不计算 / 不适用"
        state = {"ready": "已核对可比", "needs_review": "待核对", "missing": "有缺失"}.get(
            row.get("status"), "待核对"
        )
        lines.append(
            f"| {_md(row.get('label'))} | {_memo_value(row.get('current'))} | "
            f"{_memo_value(row.get('previous'))} | {pct} | {state} |"
        )
    lines += ["", "计算方法：金额先按明确单位统一为人民币元；同比 =（本期 - 上期）/ 上期 × 100%。",
              "上期为零或负数时不列增长率。优先使用较新年报中同表披露的可比期，"
              "与旧报告不同的数值会另行提示。", "", "## 基于已核对数据的事实观察", ""]
    for insight in comparison.get("insights", []):
        lines.append("- " + _md(insight))
    lines += ["", "## 来源证据与核对记录", "",
              "页码均为 PDF 文件从第一页起计数的物理页码，可能与报告印刷页码不同。", ""]
    for row in comparison.get("rows", []):
        lines += [f"### {_md(row.get('label'))}", ""]
        for period, metric in (("本期", row.get("current")), ("上期", row.get("previous"))):
            if not metric:
                lines.append(f"- {period}：未找到来源。")
                continue
            state = "已人工确认" if metric.get("status") == "confirmed" else "自动候选，尚未确认"
            lines.append(
                f"- {period} {metric.get('year')} 年：《{_md(metric.get('filename'))}》，"
                f"PDF 第 {metric.get('page') or '待确认'} 页；{state}；"
                f"币种 {_md(metric.get('currency'))}；口径 {_md(metric.get('scope'))}。"
            )
            if metric.get("evidence"):
                for evidence_line in str(metric["evidence"]).splitlines():
                    lines.append("> " + _md(evidence_line))
            if metric.get("original_value") is not None:
                lines.append(f"  原提取值：{_md(metric['original_value'])}；当前值以人工核对记录为准。")
        for note in row.get("notes", []):
            lines.append("- 核对提示：" + _md(note))
        lines.append("")
    lines += ["## 输入文件", ""]
    for report in reports:
        lines.append(
            f"- {_md(report.get('filename'))}；报告年度 {report.get('year') or '待识别'}；"
            f"PDF {report.get('page_count', 0)} 页；SHA-256：`{report.get('sha256', '未记录')}`。"
        )
        source_url = str(report.get("source_url") or "")
        if source_url.startswith(("https://", "http://")):
            lines.append("  公开来源：" + source_url)
    if comparison.get("warnings"):
        lines += ["", "## 待处理事项", ""]
        lines.extend("- " + _md(warning) for warning in comparison["warnings"])
    if ai_text.strip():
        lines += ["", "## 可选模型解读（需另行核对）", "",
                  "以下内容为模型生成，不改变上方已核对数据，也不自动构成事实或投资结论。", "",
                  ai_text.strip()]
    lines += ["", "## 适用范围", "",
              "本底稿不自动判断经营变化原因，不以缺失信息推出结论。"
              "公司主体、币种、金额单位、合并范围、调整或重述口径均需核对。", ""]
    return "\n".join(lines)
