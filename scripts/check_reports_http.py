"""Exercise the real local HTTP workflow using ONLY the bundled public demo.

--live-model explicitly sends the displayed, public-demo request to DeepSeek.
No user-uploaded document is eligible for this acceptance script.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]


def check(url: str, live_model: bool = False) -> dict:
    root = url.rstrip("/")
    token = ""

    def request(path: str, body: dict | None = None, method: str = "GET", *, auth: bool = True,
                origin: str | None = None) -> tuple[int, dict, bytes]:
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if auth and token:
            headers["X-Annual-Token"] = token
        if origin:
            headers["Origin"] = origin
        message = Request(root + path, data=data, headers=headers, method=method)
        try:
            with urlopen(message, timeout=90) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def api(path: str, body: dict | None = None, method: str = "GET") -> dict:
        status, _, data = request(path, body, method)
        value = json.loads(data)
        if status != 200:
            raise ValueError(value.get("error", "HTTP workflow failed"))
        return value

    state = api("/api/state")
    token = state["csrf_token"]
    if not state["reports"]:
        state = api("/api/demo", {}, "POST")
    manifest = json.loads((PROJECT / "data/annual_reports_demo/sources.json").read_text())
    allowed = {source["sha256"] for source in manifest["reports"]}
    if len(state["reports"]) != 2 or any(r.get("sha256") not in allowed for r in state["reports"]):
        raise ValueError("验收只可操作内置的两份公开年报，不会处理用户上传的其他资料。")
    gold = json.loads((PROJECT / "data/annual_reports_demo/golden.json").read_text())
    checks = []

    def passed(name: str, valid: bool) -> None:
        checks.append({"check": name, "passed": bool(valid)})
        if not valid:
            raise AssertionError(name)

    passed("three_native_tools", len(state["harness"]["tools"]) == 3)
    passed("missing_csrf_rejected", request("/api/ask", {"question": "你好"}, "POST", auth=False)[0] == 403)
    passed("foreign_origin_rejected", request("/api/ask", {"question": "你好"}, "POST", origin="https://example.invalid")[0] == 403)
    usage = api("/api/ask", {"question": "我该怎么使用你"}, "POST")
    passed("usage_direct_local", usage["mode"] == "local" and not usage["citations"])
    latest = max(state["reports"], key=lambda report: report["year"])
    for metric in latest["metrics"]:
        if metric.get("year") not in {2024, 2023}:
            continue
        expected = gold["metrics"][str(metric["year"])][metric["key"]]
        passed("source_amount_" + metric["key"] + str(metric["year"]),
               metric["value"] is not None and Decimal(metric["value"]) == Decimal(expected))
        api(f"/api/reports/{latest['id']}/metrics", {
            "key": metric["key"], "year": metric["year"], "value": expected,
            "unit": "元", "currency": "CNY", "scope": "consolidated", "page": 5, "status": "confirmed",
        }, "PATCH")
    state = api("/api/state")
    passed("all_six_comparisons_ready", state["comparison"]["coverage"]["ready"] == 6)
    for row in state["comparison"]["rows"]:
        passed("growth_" + row["key"], row["change_pct"] == gold["change_pct_2024"][row["key"]])
    status, headers, image = request(f"/api/reports/{latest['id']}/image/5")
    passed("source_page_png", status == 200 and image.startswith(b"\x89PNG\r\n\x1a\n"))
    passed("no_remote_assets_policy", "connect-src 'self'" in headers.get("Content-Security-Policy", ""))
    page = api(f"/api/reports/{latest['id']}/page/5")
    passed("source_page_text", page["number"] == 5 and "170,899,152,276.34" in page["text"])
    response = api("/api/ask", {"question": "2024年营业收入同比增长多少？"}, "POST")
    passed("local_growth_with_source", "15.71" in response["answer"] and bool(response["citations"]))
    for format_name in ("markdown", "csv"):
        status, headers, data = request("/api/export?format=" + format_name)
        passed("export_" + format_name, status == 200 and bool(data) and "attachment" in headers.get("Content-Disposition", ""))
    live_result = None
    if live_model:
        preview = api("/api/model-preview", {
            "question": "只根据已核对的数据，用三句话概括2024年营业收入、归母净利润和经营现金流的同比变化。请标注来源，不解释未经证实的经营原因。",
        }, "POST")
        passed("preview_excludes_credentials", "Authorization" not in json.dumps(preview["payload"]))
        passed("unapproved_send_rejected", request("/api/model-send", {
            "preview_id": preview["preview_id"], "approved": False,
        }, "POST")[0] == 400)
        live_result = api("/api/model-send", {
            "preview_id": preview["preview_id"], "approved": True,
        }, "POST")
        passed("real_deepseek_answer", live_result.get("mode") == "deepseek" and bool(live_result.get("answer")))
        passed("real_source_anchors", live_result.get("source_validation") == "anchors_valid")
        passed("one_time_preview", request("/api/model-send", {
            "preview_id": preview["preview_id"], "approved": True,
        }, "POST")[0] == 400)
    return {
        "scope": "真实本机HTTP服务；只操作两份内置公开年报；复核依据为已人工检查的PDF第5页金标准",
        "checks": checks, "passed": sum(item["passed"] for item in checks), "total": len(checks),
        "live_model_check": live_result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT / "docs/annual_reports/HTTP_ACCEPTANCE.json")
    arguments = parser.parse_args()
    result = check(arguments.url, arguments.live_model)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "total": result["total"],
                      "live_model_checked": result["live_model_check"] is not None}, ensure_ascii=False))
