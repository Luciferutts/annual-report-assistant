"""Review gates, financial edge cases, and source-preserving local answers."""

from copy import deepcopy

import pytest

from openharness.annual_reports.analysis import answer_question, build_comparison, render_markdown


def metric(key="revenue", year=2024, value="120", unit="万元", status="confirmed", **kwargs):
    return {
        "key": key, "label": "测试指标", "year": year, "value": value, "raw_value": value,
        "unit": unit, "currency": "CNY", "page": 7,
        "evidence": f"营业收入 {year} {value}", "status": status, "scope": "consolidated",
        **kwargs,
    }


def report(year=2024, metrics=None, **kwargs):
    return {
        "id": f"report{year}", "filename": f"示例公司{year}年报.pdf", "company": "示例股份有限公司",
        "year": year, "currency": "CNY", "page_count": 10, "pages": [],
        "metrics": metrics if metrics is not None else [metric(), metric(year=2023, value="100")],
        "sha256": "abc123", "source_url": "", **kwargs,
    }


def row(comparison, key="revenue"):
    return next(item for item in comparison["rows"] if item["key"] == key)


def test_decimal_unit_normalization_and_sources_are_preserved():
    source = report(metrics=[metric(value="1.2", unit="亿元"), metric(year=2023, value="10000")])
    original = deepcopy(source)
    result = build_comparison([source])
    revenue = row(result)
    assert revenue["current_yuan"] == "120000000"
    assert revenue["previous_yuan"] == "100000000"
    assert revenue["change_pct"] == "20.00"
    assert revenue["delta_yuan"] == "20000000"
    assert revenue["current"]["report_id"] == "report2024"
    assert revenue["current"]["page"] == 7
    assert source == original
    assert len(result["rows"]) == 6


def test_latest_comparable_candidate_does_not_fall_back_to_reviewed_old_number():
    latest = report(metrics=[metric(), metric(year=2023, value="110", status="candidate")])
    older = report(year=2023, metrics=[metric(year=2023, value="100")])
    revenue = row(build_comparison([older, latest]))
    assert revenue["previous"]["report_id"] == "report2024"
    assert revenue["previous"]["value"] == "110"
    assert revenue["current_yuan"] == "1200000"
    assert revenue["previous_yuan"] is None
    assert revenue["change_pct"] is None
    assert revenue["status"] == "needs_review"
    assert any("不同报告" in note for note in revenue["notes"])


@pytest.mark.parametrize("base", ["0", "-100"])
def test_nonpositive_base_has_delta_but_no_growth_rate(base):
    result = build_comparison([report(metrics=[metric(), metric(year=2023, value=base)])])
    revenue = row(result)
    assert revenue["status"] == "ready"
    assert revenue["delta_yuan"] is not None
    assert revenue["change_pct"] is None
    assert any("基数" in note for note in revenue["notes"])


def test_missing_is_not_zero_and_does_not_create_false_insight():
    result = build_comparison([report(metrics=[metric(status="candidate")])])
    assert row(result)["previous"] is None
    assert row(result)["status"] == "missing"
    assert row(result)["current_yuan"] is None
    assert result["coverage"]["ready"] == 0
    assert not any("增长" in insight or "下降" in insight for insight in result["insights"])


@pytest.mark.parametrize("changes, expected", [
    ({"company": "另一股份有限公司"}, "公司名称不同"),
    ({"currency": "USD"}, "币种不兼容"),
    ({"year": 2024}, "报告年度相同"),
    ({"year": 2022}, "相邻两年"),
])
def test_incompatible_input_reports_are_rejected(changes, expected):
    older = report(year=2023, metrics=[metric(year=2023)])
    older.update(changes)
    with pytest.raises(ValueError, match=expected):
        build_comparison([report(), older])


@pytest.mark.parametrize("name", ["未识别公司", "未知公司", "unknown", "待确认公司"])
def test_matching_placeholder_company_names_do_not_prove_same_identity(name):
    latest = report(company=name)
    older = report(year=2023, company=name, metrics=[metric(year=2023, value="100")])
    result = build_comparison([latest, older])
    assert row(result)["current_yuan"] is None
    assert row(result)["previous_yuan"] is None
    assert row(result)["change_pct"] is None
    assert result["coverage"]["ready"] == 0
    assert any("主体" in warning for warning in result["warnings"])


def test_missing_identity_and_known_identity_are_uncertain_not_mismatched():
    result = build_comparison([
        report(), report(year=2023, company="未识别公司", metrics=[metric(year=2023, value="100")]),
    ])
    assert row(result)["change_pct"] is None
    assert any("主体" in warning for warning in result["warnings"])


@pytest.mark.parametrize("changes", [
    {"scope": "parent"}, {"scope": "unknown"}, {"unit": "unknown"},
    {"currency": "unknown"}, {"page": None}, {"evidence": ""}, {"value": "NaN"},
])
def test_confirmation_alone_cannot_bypass_unknown_basis(changes):
    current = metric()
    current.update(changes)
    revenue = row(build_comparison([report(metrics=[current, metric(year=2023)])]))
    assert revenue["change_pct"] is None
    assert revenue["current_yuan"] is None
    assert revenue["notes"]


def test_same_document_conflicting_candidates_need_disambiguation():
    result = build_comparison([report(metrics=[
        metric(value="120"), metric(value="150"), metric(year=2023, value="100"),
    ])])
    assert row(result)["current_yuan"] is None
    assert row(result)["status"] == "needs_review"
    assert any("多个不同候选" in item for item in row(result)["notes"])


def test_reviewed_latest_restatement_is_used_with_conflict_warning():
    latest = report(metrics=[metric(value="120"), metric(year=2023, value="110")])
    older = report(year=2023, metrics=[metric(year=2023, value="100")])
    result = build_comparison([older, latest])
    assert row(result)["change_pct"] == "9.09"
    assert any("重述" in item for item in result["warnings"])


def test_usage_question_does_not_need_valid_report_or_any_evidence():
    result = answer_question([{"not_a_report": True}], "我该怎么使用你")
    assert result["mode"] == "local"
    assert result["citations"] == []
    assert result["needs_model"] is False
    assert "核对" in result["answer"]


def test_candidate_metric_is_labelled_and_no_unreviewed_growth_is_returned():
    result = answer_question([report(metrics=[
        metric(status="candidate"), metric(year=2023, value="100", status="candidate"),
    ])], "营业收入同比变化多少")
    assert "待核对候选" in result["answer"]
    assert "暂不计算同比" in result["answer"]
    assert "20.00%" not in result["answer"]
    assert {source["page"] for source in result["citations"]} == {7}


def test_reviewed_metric_answer_includes_growth_and_both_period_sources():
    result = answer_question([report()], "2024 年营业收入同比变化多少")
    assert "增长 20.00%" in result["answer"]
    assert len(result["citations"]) == 2
    assert all(source["report_id"] == "report2024" for source in result["citations"])


def test_question_for_older_year_does_not_receive_current_period_growth():
    source = report(metrics=[
        metric(value="120"), metric(year=2023, value="100"), metric(year=2022, value="80"),
    ])
    result = answer_question([source], "2023年营业收入同比变化多少")
    assert "2023 年：100.00" in result["answer"]
    assert "不能把它作为所问年度的同比" in result["answer"]
    assert "20.00%" not in result["answer"]
    result = answer_question([source], "2022年营业收入是多少")
    assert "2022 年：80.00" in result["answer"]
    assert "120.00" not in result["answer"]


def test_greeting_prefix_does_not_mask_actual_question():
    result = answer_question([report()], "你好，请告诉我营业收入同比变化")
    assert "增长 20.00%" in result["answer"]


def test_causal_question_retrieves_real_page_without_inventing_reason():
    source = report(pages=[{"number": 9, "text": "营业收入变动情况。本期产品销售价格发生变化。"}])
    result = answer_question([source], "营业收入增长的原因是什么")
    assert result["needs_model"] is True
    assert "不能确定经营原因" in result["answer"]
    assert result["citations"][0]["page"] == 9
    assert result["citations"][0]["evidence"] == source["pages"][0]["text"]


def test_no_evidence_does_not_turn_into_an_answer():
    result = answer_question([report()], "公司在火星开店的情况")
    assert "没有检索到足够" in result["answer"]
    assert result["citations"] == []


def test_cashflow_profit_ratio_uses_confirmed_values_only():
    source = report(metrics=[
        metric(key="operating_cashflow", value="180"),
        metric(key="profit_parent", value="120"),
    ])
    result = answer_question([source], "经营现金流和净利润的匹配情况")
    assert "1.50 倍" in result["answer"]
    source["metrics"][0]["status"] = "candidate"
    result = answer_question([source], "经营现金流和净利润的匹配情况")
    assert "1.50 倍" not in result["answer"]


def test_total_revenue_is_retrieved_not_replaced_by_operating_revenue():
    source = report(metrics=[
        metric(value="170899000000", unit="元"),
        metric(year=2023, value="150560000000", unit="元"),
    ], pages=[{"number": 8, "text": "合并利润表：营业总收入 174,144,000,000.00 元。"}])
    result = answer_question([source], "2024年营业总收入是多少")
    assert "不能用营业收入数值代替" in result["answer"]
    assert "174,144,000,000.00" in result["answer"]
    assert "170,899,000,000.00" not in result["answer"]
    assert result["citations"][0]["page"] == 8
    assert result["needs_model"] is True


@pytest.mark.parametrize("question", ["总营收是多少", "营业总收入是多少", "收入总额是多少"])
def test_broader_revenue_scope_without_source_is_not_answered_from_narrower_metric(question):
    result = answer_question([report()], question)
    assert "不能用营业收入数值代替" in result["answer"]
    assert "120.00" not in result["answer"]
    assert result["citations"] == []


@pytest.mark.parametrize("question", ["所有者权益是多少", "所有者权益合计是多少", "合并净资产是多少"])
def test_total_equity_is_not_replaced_by_attributable_equity(question):
    source = report(metrics=[
        metric(key="equity_parent", value="999"),
        metric(key="equity_parent", year=2023, value="900"),
    ], pages=[{"number": 6, "text": "合并资产负债表：所有者权益合计 1,200.00 万元。"}])
    result = answer_question([source], question)
    assert "不能用归母净资产数值代替总权益" in result["answer"]
    assert "1,200.00" in result["answer"]
    assert "999.00" not in result["answer"]
    assert result["citations"][0]["page"] == 6


def test_explicit_attributable_owner_equity_uses_the_correct_structured_metric():
    source = report(metrics=[
        metric(key="equity_parent", value="999"),
        metric(key="equity_parent", year=2023, value="900"),
    ])
    result = answer_question([source], "归属于上市公司股东的所有者权益是多少")
    assert "归母净资产：" in result["answer"]
    assert "999.00" in result["answer"]
    assert "以下仅检索原文" not in result["answer"]


def profit_report():
    return report(metrics=[
        metric(key="profit_parent", value="111"),
        metric(key="profit_parent", year=2023, value="100"),
        metric(key="profit_deducted", value="88"),
        metric(key="profit_deducted", year=2023, value="80"),
    ])


@pytest.mark.parametrize("question", [
    "扣非净利润是多少", "扣非归母净利润是多少", "扣非口径下的净利润是多少",
    "归属于上市公司股东的扣除非经常性损益的净利润是多少",
    "扣除非经常性损益后的净利润是多少", "归母净利润扣非后是多少",
])
def test_deducted_modifier_does_not_also_match_generic_net_profit(question):
    result = answer_question([profit_report()], question)
    assert "扣非归母净利润：" in result["answer"]
    assert "88.00" in result["answer"]
    assert "111.00" not in result["answer"]
    assert "\n归母净利润：" not in result["answer"]


@pytest.mark.parametrize("question", [
    "归母净利润和扣非净利润分别多少", "比较扣非归母净利润与归母净利润", "扣非和净利润分别多少",
])
def test_explicit_profit_comparison_keeps_both_attributable_and_deducted_values(question):
    result = answer_question([profit_report()], question)
    assert "归母净利润：" in result["answer"]
    assert "扣非归母净利润：" in result["answer"]
    assert "111.00" in result["answer"]
    assert "88.00" in result["answer"]


def test_generic_net_profit_is_explicitly_labelled_as_attributable_not_consolidated():
    result = answer_question([profit_report()], "净利润是多少")
    assert "归属于上市公司股东的净利润" in result["answer"]
    assert "不等同于包含少数股东损益的合并净利润" in result["answer"]
    assert "111.00" in result["answer"]
    assert "88.00" not in result["answer"]


@pytest.mark.parametrize("question", ["合并净利润是多少", "净利润合计是多少", "利润总额是多少"])
def test_total_profit_scope_never_silently_uses_attributable_profit(question):
    source = profit_report()
    source["pages"] = [{"number": 5, "text": "合并利润表：净利润合计 130.00 万元，利润总额 150.00 万元。"}]
    result = answer_question([source], question)
    assert "不能用归母数值代答" in result["answer"]
    assert "111.00" not in result["answer"]
    assert result["citations"][0]["page"] == 5


def test_generic_net_assets_are_explicitly_labelled_as_attributable():
    source = report(metrics=[metric(key="equity_parent", value="999")])
    result = answer_question([source], "净资产是多少")
    assert "净资产指归属于上市公司股东的净资产" in result["answer"]
    assert "不作为所有者权益合计展示" in result["answer"]
    assert "999.00" in result["answer"]


@pytest.mark.parametrize("question, source_text", [
    ("投资现金流是多少", "投资活动产生的现金流量净额 -35.00 万元。"),
    ("筹资现金流是多少", "筹资活动产生的现金流量净额 20.00 万元。"),
    ("投资活动产生的现金流量净额是多少", "投资活动产生的现金流量净额 -35.00 万元。"),
    ("筹资活动现金流净额是多少", "筹资活动现金流净额 20.00 万元。"),
])
def test_nonoperating_cashflow_does_not_receive_operating_cashflow(question, source_text):
    source = report(metrics=[
        metric(key="operating_cashflow", value="180"),
        metric(key="operating_cashflow", year=2023, value="160"),
    ], pages=[{"number": 9, "text": source_text}])
    result = answer_question([source], question)
    assert "不能用经营现金流数值代答" in result["answer"]
    assert "180.00" not in result["answer"]
    assert result["citations"][0]["page"] == 9


def test_generic_cashflow_is_explicitly_labelled_as_operating_net_flow():
    source = report(metrics=[metric(key="operating_cashflow", value="180")])
    result = answer_question([source], "现金流是多少")
    assert "按当前结构化字段“经营活动产生的现金流量净额”展示" in result["answer"]
    assert "不代表投资、筹资活动现金流" in result["answer"]
    assert "180.00" in result["answer"]


@pytest.mark.parametrize("question, source_text", [
    ("2024年第四季度营收是多少", "第四季度：营业收入 30.00 万元。"),
    ("2024年上半年营业收入是多少", "2024年上半年营业收入 55.00 万元。"),
    ("2024年半年度营收是多少", "半年度主要会计数据：营业收入 55.00 万元。"),
    ("2024年6月营业收入是多少", "2024年6月营业收入 8.00 万元。"),
    ("月度营业收入是多少", "月度营业收入：六月 8.00 万元。"),
])
def test_subannual_question_never_uses_annual_structured_number(question, source_text):
    source = report(pages=[{"number": 9, "text": source_text}])
    result = answer_question([source], question)
    assert "不能用全年数值代答" in result["answer"]
    assert "120.00" not in result["answer"]
    assert result["citations"][0]["page"] == 9


@pytest.mark.parametrize("question, source_text", [
    ("分产品营业收入是多少", "分产品：产品甲营业收入 70.00 万元。"),
    ("按地区营收对比", "按地区列示营业收入：地区甲 60.00 万元。"),
    ("直销营业收入是多少", "直销营业收入 45.00 万元。"),
    ("批发渠道营收是多少", "批发渠道营业收入 75.00 万元。"),
    ("国内营业收入是多少", "国内营业收入 110.00 万元。"),
    ("国外营业收入是多少", "国外营业收入 10.00 万元。"),
])
def test_segment_question_never_receives_companywide_number(question, source_text):
    source = report(pages=[{"number": 9, "text": source_text}])
    result = answer_question([source], question)
    assert "不能用公司总数代答" in result["answer"]
    assert "120.00" not in result["answer"]
    assert result["citations"][0]["page"] == 9


@pytest.mark.parametrize("question", ["母公司营业收入是多少", "单体口径营业收入是多少", "非合并口径营收是多少"])
def test_parent_only_request_does_not_receive_consolidated_revenue(question):
    source = report(pages=[{"number": 9, "text": "母公司及单体利润表：营业收入 40.00 万元。"}])
    result = answer_question([source], question)
    assert "不能用合并数值代答" in result["answer"]
    assert "120.00" not in result["answer"]
    assert result["citations"][0]["page"] == 9


def test_attributable_to_parent_wording_does_not_trigger_parent_statement_guard():
    result = answer_question([profit_report()], "归属于母公司股东的净利润是多少")
    assert "111.00" in result["answer"]
    assert "不能用合并数值代答" not in result["answer"]


def test_year_end_balance_date_is_not_misclassified_as_monthly_income():
    source = report(metrics=[metric(key="total_assets", value="900")])
    result = answer_question([source], "2024年12月31日总资产是多少")
    assert "900.00" in result["answer"]
    assert "不能用全年数值代答" not in result["answer"]


def test_month_end_asset_request_does_not_receive_annual_closing_assets():
    source = report(metrics=[metric(key="total_assets", value="900")], pages=[
        {"number": 9, "text": "6月末总资产 650.00 万元。"},
    ])
    result = answer_question([source], "2024年6月末总资产是多少")
    assert "不能用全年数值代答" in result["answer"]
    assert "900.00" not in result["answer"]
    assert result["citations"][0]["page"] == 9


def test_markdown_export_keeps_candidates_sources_and_model_section_separate():
    source = report(metrics=[metric(status="candidate"), metric(year=2023, value="100")])
    result = render_markdown(build_comparison([source]), [source], "需要再次核对的模型解读。")
    assert "待核对候选" in result
    assert "PDF 第 7 页" in result
    assert "营业收入 2024 120" in result
    assert "SHA-256：`abc123`" in result
    assert "## 可选模型解读（需另行核对）" in result
    assert "20.00%" not in result
