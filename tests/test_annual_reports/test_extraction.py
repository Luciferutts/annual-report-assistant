"""Financial extraction tests protect column, unit and source correctness."""

from pathlib import Path

import pytest

from openharness.annual_reports.extraction import extract_report, extract_text_pages, parse_decimal


def document(body: str, *, title="示例科技股份有限公司", year=2024, page=5):
    return extract_text_pages([
        {"number": 1, "text": f"{title}\n{year}年年度报告\n公司代码：600001\n本年度报告包含主要会计数据和财务指标，所有自动提取数据均须核对原文后确认。"},
        {"number": page, "text": body},
    ], f"example-{year}.pdf")


def metric(report, key, year=2024):
    return next(item for item in report["metrics"] if item["key"] == key and item["year"] == year)


@pytest.mark.parametrize(("raw", "expected"), [
    ("1,234,567.89", "1234567.89"), ("（1,234.50）", "-1234.50"),
    ("−123.00", "-123.00"), ("0", "0"), ("—", None), ("NaN", None),
    ("12.50%", None), ("1，234.05", "1234.05"),
])
def test_decimal_parsing_preserves_precision_and_missing(raw, expected):
    assert parse_decimal(raw) == expected


def test_comparison_growth_column_is_not_an_older_year_amount():
    report = document("""主要会计数据
单位：万元 币种：人民币
项目              2024年              2023年      本期比上年增减(%)      2022年
营业收入          123,456.78          100,000.00     23.46             90,000.00
总资产            400,000.00          350,000.00     14.29             300,000.00
""")
    assert metric(report, "revenue")["value"] == "123456.78"
    assert metric(report, "revenue", 2023)["value"] == "100000.00"
    assert metric(report, "revenue", 2022)["value"] == "90000.00"
    assert metric(report, "revenue")["unit"] == "万元"
    assert metric(report, "revenue")["page"] == 5
    assert metric(report, "revenue")["status"] == "candidate"
    assert metric(report, "revenue")["evidence"] in report["pages"][1]["text"]


def test_interleaved_wrapped_label_is_a_single_row():
    report = document("""主要会计数据
单位：元 币种：人民币
项目           2024年         2023年      本期比上年增减(%)      2022年
归属于上市公
司股东的扣除   12,345.00      10,000.00     23.45              9,000.00
非经常性损益
的净利润
归属于上市公司股东的净    13,000.00    11,000.00    18.18    8,000.00
利润
归属于上市公司股东的净    60,000.00    50,000.00    20.00    40,000.00
资产
""")
    assert metric(report, "profit_deducted")["value"] == "12345.00"
    assert metric(report, "profit_parent")["value"] == "13000.00"
    assert metric(report, "equity_parent")["value"] == "60000.00"
    assert "非经常性损益\n的净利润" in metric(report, "profit_deducted")["evidence"]


def test_restated_history_is_not_silently_selected():
    report = document("""主要会计数据
单位：元 币种：人民币
项目           2024年         2023年       本期比上年增减(%)       2022年
                          调整后  调整前                       调整后 调整前
营业收入       1,200.00       1,000.00  999.00    20.00             900.00  899.00
""")
    assert metric(report, "revenue")["value"] == "1200.00"
    assert metric(report, "revenue", 2023)["value"] is None
    assert any("调整前/后" in warning for warning in report["warnings"])


def test_split_balance_header_reconstructs_current_year_column():
    report = document("""主要会计数据
单位：元 币种：人民币
                          2023年末              本期末比上       2022年末
               2024年末                        年同期末增
                     调整后   调整前            减（%）       调整后 调整前
总资产         1,200.00  1,000.00  999.00        20.00           900.00  899.00
""")
    assert metric(report, "total_assets")["value"] == "1200.00"
    assert metric(report, "total_assets", 2023)["value"] is None


def test_missing_current_cell_does_not_shift_prior_value():
    report = document("""主要会计数据
单位：元 币种：人民币
项目           2024年         2023年       本期比上年增减(%)       2022年
营业收入       —              1,000.00      —                    900.00
""")
    assert metric(report, "revenue")["status"] == "missing"
    assert metric(report, "revenue", 2023)["value"] == "1000.00"
    assert metric(report, "revenue", 2022)["value"] == "900.00"


def test_blank_current_column_without_marker_requires_manual_entry():
    report = document("""主要会计数据
单位：元 币种：人民币
项目           2024年         2023年
营业收入                     1,000.00
""")
    assert metric(report, "revenue")["status"] == "missing"
    assert metric(report, "revenue")["value"] is None


def test_unexplained_numeric_footnote_column_is_not_a_money_value():
    report = document("""合并利润表
单位：元 币种：人民币
项目     附注      2024年度         2023年度
营业收入 五、61    1,234.00         1,000.00
""")
    assert metric(report, "revenue")["status"] == "missing"


def test_parent_statement_is_excluded_from_consolidated_candidates():
    report = document("""母公司利润表
单位：元 币种：人民币
项目           2024年度         2023年度
营业收入       1,234.00         1,000.00
""")
    assert metric(report, "revenue")["status"] == "missing"
    assert metric(report, "revenue")["value"] is None


def test_conflicting_equal_priority_data_requires_manual_entry():
    report = document("""主要会计数据
单位：元 币种：人民币
项目           2024年         2023年
营业收入       1,234.00       1,000.00
营业收入       2,000.00       1,000.00
""")
    assert metric(report, "revenue")["status"] == "missing"
    assert metric(report, "revenue")["page"] == 5
    assert any("冲突" in warning for warning in report["warnings"])


def test_unknown_unit_and_foreign_currency_are_not_assumed_cny():
    report = document("""主要会计数据
币种：美元
项目           2024年         2023年
营业收入       1,234.00       1,000.00
""")
    record = metric(report, "revenue")
    assert record["unit"] == "unknown"
    assert record["currency"] == "unknown"


def test_negative_cashflow_is_preserved():
    report = document("""主要会计数据
单位：亿元 币种：人民币
项目           2024年         2023年
经营活动产生的现金流量净额       (12.50)       -8.25
""")
    assert metric(report, "operating_cashflow")["value"] == "-12.50"
    assert metric(report, "operating_cashflow", 2023)["value"] == "-8.25"


def test_non_text_scan_is_actionable():
    with pytest.raises(ValueError, match="OCR"):
        extract_text_pages([{"number": 1, "text": ""}], "scan-2024.pdf")


def test_scanned_body_with_only_text_cover_requires_ocr():
    pages = [{"number": 1, "text": "示例科技股份有限公司2024年年度报告" * 4}]
    pages.extend({"number": number, "text": f"第 {number} 页"} for number in range(2, 12))
    with pytest.raises(ValueError, match="OCR"):
        extract_text_pages(pages, "scan-2024.pdf")


def test_half_year_report_is_not_an_annual_comparison():
    with pytest.raises(ValueError, match="半年报"):
        extract_text_pages([{"number": 1, "text": "示例科技股份有限公司2024年半年度报告" * 4}], "2024.pdf")


def test_invalid_file_is_actionable(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"not a PDF")
    with pytest.raises(ValueError, match="有效 PDF"):
        extract_report(path)


@pytest.mark.parametrize(("year", "revenue", "profit", "cashflow", "assets", "equity"), [
    (2024, "170899152276.34", "86228146421.62", "92463692168.43", "298944579918.70", "233105984399.47"),
    (2023, "147693604994.14", "74734071550.75", "66593247721.09", "272699660092.25", "215668571607.43"),
])
def test_real_public_chinese_annual_reports(year, revenue, profit, cashflow, assets, equity):
    path = Path(__file__).parents[2] / "data" / "annual_reports_demo" / f"moutai-{year}.pdf"
    if not path.exists():
        pytest.skip("Official demonstration PDF is not installed")
    report = extract_report(path)
    assert report["year"] == year
    assert report["company"] == "贵州茅台酒股份有限公司"
    for key, expected in {"revenue": revenue, "profit_parent": profit,
                          "operating_cashflow": cashflow, "total_assets": assets,
                          "equity_parent": equity}.items():
        record = metric(report, key, year)
        assert record["value"] == expected
        assert record["page"] == 5
        assert record["status"] == "candidate"
        assert record["scope"] == "consolidated"
        assert record["unit"] == "元"
        assert record["currency"] == "CNY"
