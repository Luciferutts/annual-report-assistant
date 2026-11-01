"""Reproducible offline acceptance against manually checked public source pages."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from openharness.annual_reports.analysis import render_markdown  # noqa: E402
from openharness.annual_reports.server import AnnualReportApplication, _csv  # noqa: E402


def evaluate() -> dict:
    golden = json.loads((PROJECT / "data/annual_reports_demo/golden.json").read_text())
    checks = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="annual-report-evaluation-") as temporary:
        app = AnnualReportApplication(Path(temporary), PROJECT)
        app.load_demo()
        extraction_seconds = round(time.perf_counter() - started, 3)
        reports = app.store.documents()
        for report in reports:
            for metric in report["metrics"]:
                expected = golden["metrics"].get(str(metric["year"]), {}).get(metric["key"])
                if expected is None:
                    continue
                actual = metric.get("value")
                checks.append({
                    "report": report["filename"], "year": metric["year"], "metric": metric["key"],
                    "expected": expected, "actual": actual,
                    "correct": actual is not None and Decimal(actual) == Decimal(expected),
                    "source_correct": metric.get("page") == golden["pdf_page"]
                    and metric.get("unit") == "元" and metric.get("currency") == "CNY"
                    and metric.get("scope") == "consolidated" and bool(metric.get("evidence")),
                })
        before = app.state()
        assert before["comparison"]["coverage"]["ready"] == 0, "自动候选不得直接进入正式计算"
        latest = max(reports, key=lambda report: report["year"])
        # These are acceptance-review actions against the separately inspected
        # gold pages, not automatic confirmation in the extraction product.
        for metric in latest["metrics"]:
            if metric.get("year") not in {2024, 2023} or metric.get("value") is None:
                continue
            expected = golden["metrics"][str(metric["year"])][metric["key"]]
            assert Decimal(metric["value"]) == Decimal(expected)
            app.store.confirm_metric(latest["id"], {
                "key": metric["key"], "year": metric["year"], "value": expected,
                "unit": "元", "currency": "CNY", "scope": "consolidated",
                "page": 5, "status": "confirmed",
            })
        final = app.state()
        comparison = final["comparison"]
        growth_checks = [{
            "metric": row["key"], "actual": row["change_pct"],
            "expected": golden["change_pct_2024"][row["key"]],
            "correct": row["change_pct"] == golden["change_pct_2024"][row["key"]],
        } for row in comparison["rows"]]
        qa_cases = [
            ("使用说明", "我该怎么使用你", "先上传", False),
            ("隐私边界", "数据会发给模型吗", "确认", False),
            ("营收同比", "2024年营业收入同比增长多少", "15.71", True),
            ("归母同比", "归母净利润同比变化多少", "15.38", True),
            ("扣非同比", "扣非净利润同比变化多少", "15.37", True),
            ("现金流同比", "经营现金流同比变化多少", "38.85", True),
            ("总资产同比", "总资产同比变化多少", "9.62", True),
            ("净资产同比", "归母净资产同比变化多少", "8.09", True),
            ("不存在的年度", "2099年营业收入是多少", "没有找到", False),
            ("历史同比边界", "2023年营业收入同比是多少", "不能把它作为所问年度的同比", True),
            ("经营原因证据", "2024年营业收入增长的原因是什么", "原文", True),
        ]
        qa_checks = []
        for name, question, expected, wants_source in qa_cases:
            response = app.tool_output("annual_report_search", {"question": question})
            correct = expected in response["answer"] and response["mode"] == "local"
            if wants_source:
                correct = correct and bool(response.get("citations"))
            qa_checks.append({"case": name, "question": question, "correct": bool(correct),
                              "source_count": len(response.get("citations", []))})
        output = PROJECT / "outputs/annual_reports"
        output.mkdir(parents=True, exist_ok=True)
        (output / "贵州茅台2024对比2023-示例底稿.md").write_text(
            render_markdown(comparison, app.store.documents()), encoding="utf-8")
        (output / "贵州茅台2024对比2023-示例指标.csv").write_text(_csv(comparison), encoding="utf-8")
        result = {
            "evaluated_at": "2026-11-01", "scope": "同一家中文上市公司两份历史年报，非通用准确率基准",
            "source_reports": len(reports), "source_pages_manually_reviewed": ["2024 PDF p5", "2023 PDF p5"],
            "extraction_seconds": extraction_seconds,
            "amount_checks": checks, "growth_checks": growth_checks, "local_qa_checks": qa_checks,
            "summary": {
                "amounts_checked": len(checks), "amounts_correct": sum(item["correct"] for item in checks),
                "sources_correct": sum(item["source_correct"] for item in checks),
                "growth_checked": len(growth_checks), "growth_correct": sum(item["correct"] for item in growth_checks),
                "local_qa_checked": len(qa_checks), "local_qa_passed": sum(item["correct"] for item in qa_checks),
                "review_gate_before": before["comparison"]["coverage"]["ready"],
                "review_gate_after": comparison["coverage"]["ready"],
                "registered_tools": final["harness"]["tools"],
            },
            "limitations": [
                "金额金标准由人工核对原PDF第5页建立；样本仅1家公司2份年报。",
                "没有用户计时对照实验，不能据此声称节省时间或提高研究效率百分比。",
                "本评测不调用模型；模型解读需要另行验证，且不能替代财务复核。",
            ],
        }
    (PROJECT / "docs/annual_reports/EVALUATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = evaluate()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    checks = result["amount_checks"] + result["growth_checks"] + result["local_qa_checks"]
    raise SystemExit(0 if all(item["correct"] for item in checks) else 1)
