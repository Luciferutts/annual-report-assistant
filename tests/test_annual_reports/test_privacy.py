"""Privacy boundaries: explicit egress consent, source integrity and local HTTP isolation."""

from copy import deepcopy
import csv
from decimal import Decimal
from email.message import Message
import hashlib
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from openharness.annual_reports import model, server, store as storage


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                 "OPENHARNESS_MODEL", "OPENHARNESS_BASE_URL", "OPENHARNESS_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-credential-never-in-payload")
    monkeypatch.setattr(model, "build_opener", lambda *args, **kwargs: SimpleNamespace(
        open=lambda *args, **kwargs: pytest.fail("Unexpected network request"),
    ))


@pytest.fixture
def report():
    return {
        "id": "a" * 20, "filename": "示例公司2024年报.pdf", "company": "示例科技股份有限公司",
        "year": 2024, "currency": "CNY", "page_count": 2,
        "local_path": "/private/never-send-this-path/report.pdf",
        "pages": [{"number": 1, "text": "未选中的内部信息 do-not-send-unselected-text"},
                  {"number": 2, "text": "主要会计数据 单位：元 币种：人民币\n2024年 2023年\n营业收入 1,000.00 900.00\n经营现金流量净额 （123.50） -80.00"}],
        "metrics": [{"key": "revenue", "label": "营业收入", "year": 2024,
                     "value": "1000.00", "raw_value": "1,000.00", "unit": "元", "currency": "CNY",
                     "page": 2, "evidence": "营业收入 1,000.00 900.00", "status": "candidate",
                     "scope": "consolidated"}],
        "warnings": [], "source_url": "", "sha256": "a" * 64,
    }


@pytest.fixture
def preview_setup(monkeypatch, report):
    monkeypatch.setattr(model, "model_status", lambda: {
        "configured": True, "provider": "deepseek", "model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
    })
    calls = []

    def sender(payload):
        calls.append(deepcopy(payload))
        return {"answer": "营业收入来源见 [R1·PDF第2页]。", "usage": {"total_tokens": 10}}

    version = ["initial-state"]
    manager = model.PreviewManager(lambda: version[0], sender=sender)
    local = {"citations": [{"report_id": report["id"], "page": 2,
                             "evidence": "营业收入 1,000.00 900.00"}]}
    return manager, calls, version, local


def make_preview(preview_setup, report):
    manager, _, _, local = preview_setup
    return manager.create("营业收入有什么变化？", [report], None, local)


def test_preview_never_sends_and_excludes_unselected_context(preview_setup, report):
    preview = make_preview(preview_setup, report)
    _, calls, _, _ = preview_setup
    serialized = json.dumps(preview, ensure_ascii=False)
    assert calls == []
    assert "unit-test-credential-never-in-payload" not in serialized
    assert "do-not-send-unselected-text" not in serialized
    assert "never-send-this-path" not in serialized
    assert "tools" not in preview["payload"]
    assert "营业收入 1,000.00 900.00" in serialized
    assert preview["provider"] == "deepseek"


@pytest.mark.parametrize("approval", [False, None, 1, "true", {}, []])
def test_explicit_boolean_approval_is_required(preview_setup, report, approval):
    preview = make_preview(preview_setup, report)
    manager, calls, _, _ = preview_setup
    with pytest.raises(ValueError, match="未确认"):
        manager.send(preview["preview_id"], approval)
    assert calls == []


def test_sender_receives_exact_immutable_preview_payload_once(preview_setup, report):
    preview = make_preview(preview_setup, report)
    original = deepcopy(preview["payload"])
    original_json = json.dumps(original, ensure_ascii=False, indent=2)
    assert hashlib.sha256(original_json.encode()).hexdigest() == preview["payload_sha256"]
    preview["payload"]["messages"][1]["content"] = "try to substitute another upload"
    preview["payload"]["model"] = "not-the-approved-model"
    manager, calls, _, _ = preview_setup
    result = manager.send(preview["preview_id"], True)
    assert calls == [original]
    assert result["source_validation"] == "anchors_valid"
    with pytest.raises(ValueError, match="已经使用|失效"):
        manager.send(preview["preview_id"], True)
    assert len(calls) == 1


def test_preview_expiration_prevents_sending(preview_setup, report, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(model.time, "time", lambda: now[0])
    preview = make_preview(preview_setup, report)
    now[0] += 601
    manager, calls, _, _ = preview_setup
    with pytest.raises(ValueError, match="重新预览"):
        manager.send(preview["preview_id"], True)
    assert calls == []


def test_changed_review_state_invalidates_previous_approval(preview_setup, report):
    preview = make_preview(preview_setup, report)
    manager, calls, version, _ = preview_setup
    version[0] = "reviewed-data-changed"
    with pytest.raises(ValueError, match="已变化"):
        manager.send(preview["preview_id"], True)
    assert calls == []


def test_clear_preview_prevents_reuse_after_deletion(preview_setup, report):
    preview = make_preview(preview_setup, report)
    manager, calls, _, _ = preview_setup
    manager.clear()
    with pytest.raises(ValueError, match="失效"):
        manager.send(preview["preview_id"], True)
    assert calls == []


def test_missing_or_forged_source_cannot_create_sendable_preview(preview_setup, report):
    manager, calls, _, _ = preview_setup
    for citations in ([], [{"report_id": "b" * 20, "page": 2}],
                      [{"report_id": report["id"], "page": 999}]):
        with pytest.raises(ValueError, match="原文依据"):
            manager.create("解释收入", [report], None, {"citations": citations})
    assert calls == []


def test_model_cannot_cite_a_page_absent_from_preview(preview_setup, report):
    manager, calls, _, _ = preview_setup

    def false_source(payload):
        calls.append(payload)
        return {"answer": "不存在的资料支持该结论 [R99·PDF第999页]"}

    manager._sender = false_source
    preview = make_preview(preview_setup, report)
    with pytest.raises(ValueError, match="来源页|来源编号"):
        manager.send(preview["preview_id"], True)
    assert len(calls) == 1


def test_model_answer_without_anchors_is_labeled_unverified(preview_setup, report):
    manager, _, _, _ = preview_setup
    manager._sender = lambda payload: {"answer": "这是一段没有来源标记的解释。"}
    preview = make_preview(preview_setup, report)
    result = manager.send(preview["preview_id"], True)
    assert result["source_validation"] == "missing_anchors"
    assert "没有给出" in result["notice"]


def test_page_limit_excludes_facts_whose_sources_are_not_in_preview(report):
    report = deepcopy(report)
    report["pages"] = [{"number": number, "text": f"第{number}页公开财务数据"}
                       for number in range(1, 10)]
    report["page_count"] = len(report["pages"])
    local = {"citations": [{"report_id": report["id"], "page": number,
                             "evidence": f"第{number}页公开财务数据"}
                            for number in range(1, 7)]}

    def row(label, first_page, second_page):
        return {
            "label": label, "status": "ready", "current_yuan": "1000.00",
            "previous_yuan": "900.00", "change_pct": "11.11", "delta_yuan": "100.00",
            "current": {"report_id": report["id"], "page": first_page},
            "previous": {"report_id": report["id"], "page": second_page}, "notes": [],
        }

    comparison = {"current_year": 2024, "previous_year": 2023,
                  "rows": [row("营业收入", 1, 2), row("归母净利润", 5, 6), row("总资产", 7, 8)]}
    payload, citations = model.make_payload("比较主要指标", [report], comparison, local, "deepseek-flash")
    content = json.loads(payload["messages"][1]["content"])
    selected_sources = {item["source_label"] for item in citations}
    assert len(citations) == 6
    assert {fact["metric"] for fact in content["confirmed_financial_facts"]} == {"营业收入", "归母净利润"}
    assert all(set(fact["sources"]) <= selected_sources
               for fact in content["confirmed_financial_facts"])
    assert any("总资产" in pending and "来源不在" in pending
               for pending in content["unreviewed_or_missing_metrics"])


def configure(monkeypatch, *, base="https://api.deepseek.com/v1", key="test-private-key"):
    settings = SimpleNamespace(
        model_copy=lambda **kwargs: settings,
        resolve_profile=lambda name: (name, SimpleNamespace(base_url=base, resolved_model="deepseek-flash")),
        resolve_auth=lambda: SimpleNamespace(value=key),
    )
    monkeypatch.setattr(model, "load_settings", lambda: settings)


@pytest.mark.parametrize("base", [
    "http://api.deepseek.com/v1", "https://evil.example/v1",
    "https://api.deepseek.com.evil.example/v1", "https://user:password@api.deepseek.com/v1",
    "https://api.deepseek.com:8443/v1", "https://api.deepseek.com/v1?redirect=evil",
    "https://api.deepseek.com/v1#fragment", "https://api.deepseek.com/unexpected-path",
])
def test_model_configuration_rejects_unapproved_destination(monkeypatch, base):
    configure(monkeypatch, base=base)
    with pytest.raises(ValueError, match="官方|格式"):
        model._configuration()


def test_model_status_never_returns_credentials(monkeypatch):
    configure(monkeypatch, key="credential-that-must-stay-server-side")
    status = model.model_status()
    assert status["configured"] is True
    assert "credential-that-must-stay-server-side" not in json.dumps(status)
    assert "key" not in status and "api_key" not in status


def test_deepseek_transport_keeps_credential_in_header_only_and_disables_redirects(monkeypatch):
    configure(monkeypatch, key="transport-private-credential")
    payload = {"model": "deepseek-flash", "messages": [{"role": "user", "content": "已批准的内容"}]}
    calls = []
    handlers = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            assert limit <= 2 * 1024 * 1024 + 1
            return json.dumps({"choices": [{"message": {"content": "回答"}}]}).encode()

    def open_request(request, timeout):
        calls.append(request)
        assert timeout == 45
        return Response()

    def opener(*configured_handlers):
        handlers.extend(configured_handlers)
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(model, "build_opener", opener)
    result = model.call_deepseek(payload)
    assert result["answer"] == "回答"
    assert calls[0].full_url == "https://api.deepseek.com/v1/chat/completions"
    assert calls[0].get_header("Authorization") == "Bearer transport-private-credential"
    assert json.loads(calls[0].data) == payload
    assert b"transport-private-credential" not in calls[0].data
    assert any(isinstance(item, model.NoRedirects) for item in handlers)
    assert model.NoRedirects().redirect_request(
        Request("https://api.deepseek.com/v1/chat/completions"), None, 302,
        "Found", {}, "https://evil.example/collect",
    ) is None


def test_model_configuration_change_cannot_reuse_old_preview_model(monkeypatch):
    configure(monkeypatch)
    with pytest.raises(ValueError, match="配置已变化"):
        model.call_deepseek({"model": "another-model", "messages": []})


def test_model_http_failure_does_not_return_provider_error_body_or_secret(monkeypatch):
    configure(monkeypatch, key="transport-private-credential")

    def fail(request, **kwargs):
        raise HTTPError(request.full_url, 401, "provider-secret-error-body", {}, None)

    monkeypatch.setattr(model, "build_opener", lambda *args: SimpleNamespace(open=fail))
    with pytest.raises(ValueError) as failure:
        model.call_deepseek({"model": "deepseek-flash", "messages": []})
    assert "密钥无效" in str(failure.value)
    assert "transport-private-credential" not in str(failure.value)
    assert "provider-secret-error-body" not in str(failure.value)


@pytest.fixture
def local_store(tmp_path, monkeypatch, report):
    monkeypatch.setattr(storage, "extract_report", lambda *args, **kwargs: {
        **deepcopy(report), "filename": kwargs["filename"],
    })
    result = storage.ReportStore(tmp_path / "workspace")
    added = result.add_pdf(b"%PDF-1.7\nlocal-fixture", "../../outside/report.pdf")
    return result, added


def update(**overrides):
    return {"key": "revenue", "year": 2024, "value": "1000.00", "unit": "元",
            "currency": "CNY", "page": 2, "scope": "consolidated", "status": "confirmed",
            **overrides}


def test_uploaded_filename_cannot_choose_storage_path(local_store, tmp_path):
    workspace, report = local_store
    assert report["filename"] == "report.pdf"
    assert sorted(path.name for path in workspace.root.iterdir()) == [
        report["id"] + ".json", report["id"] + ".pdf",
    ]
    assert not (tmp_path / "outside").exists()
    assert workspace.root.stat().st_mode & 0o777 == 0o700
    for path in workspace.root.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600


def test_confirmation_requires_a_number_on_the_selected_source_page(local_store):
    workspace, report = local_store
    fingerprint = workspace.fingerprint()
    with pytest.raises(ValueError, match="未找到这个金额"):
        workspace.confirm_metric(report["id"], update(value="999999.99"))
    assert workspace.fingerprint() == fingerprint
    with pytest.raises(ValueError, match="未找到这个金额"):
        workspace.confirm_metric(report["id"], update(page=1))


@pytest.mark.parametrize("change", [
    {"key": "arbitrary_tool"}, {"page": 0}, {"page": 3}, {"page": True},
    {"year": 2030}, {"year": True}, {"currency": "USD"}, {"unit": "unknown"},
    {"scope": "unknown"}, {"status": "candidate"}, {"value": "NaN"}, {"value": "12%"},
])
def test_confirmation_rejects_invalid_dimensions(local_store, change):
    workspace, report = local_store
    before = workspace.fingerprint()
    with pytest.raises(ValueError):
        workspace.confirm_metric(report["id"], update(**change))
    assert workspace.fingerprint() == before


def test_confirmed_metric_keeps_original_and_audit_record(local_store):
    workspace, report = local_store
    workspace.confirm_metric(report["id"], update())
    saved = workspace.get(report["id"])
    item = next(metric for metric in saved["metrics"] if metric["key"] == "revenue")
    assert item["status"] == "confirmed"
    assert item["original_extraction"]["status"] == "candidate"
    assert "1,000.00" in item["evidence"]
    assert saved["audit"][-1]["action"] == "confirm_metric"


def test_positive_amount_cannot_be_confirmed_from_negative_parentheses():
    text = "经营活动现金流量净额 （1,234.50）"
    assert "（1,234.50）" in storage.evidence_for_value(text, Decimal("-1234.50"))
    with pytest.raises(ValueError, match="未找到"):
        storage.evidence_for_value(text, Decimal("1234.50"))


@pytest.mark.parametrize("suffix", ["%", "％"])
def test_percentage_is_not_amount_evidence(suffix):
    with pytest.raises(ValueError, match="未找到"):
        storage.evidence_for_value("本期同比增长 12.50" + suffix, Decimal("12.50"))


def test_source_excerpt_contains_match_even_on_long_line():
    evidence = storage.evidence_for_value("说明" * 2000 + "营业收入 1,234.50 900.00", Decimal("1234.50"))
    assert "1,234.50" in evidence
    assert len(evidence) <= 800


def test_get_and_documents_cannot_mutate_persisted_source(local_store):
    workspace, report = local_store
    before = workspace.fingerprint()
    workspace.get(report["id"])["metrics"][0]["value"] = "999999"
    workspace.documents()[0]["pages"][1]["text"] = "tampered"
    assert workspace.fingerprint() == before
    assert workspace.get(report["id"])["pages"][1]["text"].startswith("主要会计数据")


@pytest.mark.parametrize("report_id", ["../outside", "a" * 20 + "/../outside", "/etc/passwd", "a" * 19])
def test_report_id_cannot_escape_workspace(local_store, report_id):
    workspace, _ = local_store
    with pytest.raises(ValueError):
        workspace.get(report_id)
    with pytest.raises(ValueError):
        workspace.delete(report_id)


def test_delete_removes_only_selected_uploaded_data(local_store, tmp_path):
    workspace, report = local_store
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep")
    workspace.delete(report["id"])
    assert workspace.documents() == []
    assert list(workspace.root.iterdir()) == []
    assert unrelated.read_text() == "keep"


def test_failed_upload_does_not_leave_pdf_or_json(tmp_path, monkeypatch):
    workspace = storage.ReportStore(tmp_path / "workspace")

    def fail(*args, **kwargs):
        raise ValueError("PDF 无法解析")

    monkeypatch.setattr(storage, "extract_report", fail)
    with pytest.raises(ValueError, match="无法解析"):
        workspace.add_pdf(b"%PDF-1.7\nbroken", "broken.pdf")
    assert list(workspace.root.iterdir()) == []


def handler(*, host="127.0.0.1:8787", origin="http://127.0.0.1:8787", token="session-token"):
    result = object.__new__(server.ReportHandler)
    result.server = SimpleNamespace(
        server_address=("127.0.0.1", 8787), application=SimpleNamespace(token="session-token"),
    )
    result.headers = Message()
    result.headers["Host"] = host
    if origin is not None:
        result.headers["Origin"] = origin
    if token is not None:
        result.headers["X-Annual-Token"] = token
    return result


@pytest.mark.parametrize("host", ["evil.example:8787", "127.0.0.1.evil.example:8787", "127.0.0.1", "localhost:80"])
def test_http_rejects_unexpected_host_even_with_valid_token(host):
    with pytest.raises(PermissionError, match="本机"):
        handler(host=host)._check_mutation()


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:9999"])
def test_http_rejects_cross_origin_even_with_valid_token(origin):
    with pytest.raises(PermissionError, match="来源"):
        handler(origin=origin)._check_mutation()


@pytest.mark.parametrize("token", [None, "", "old-session-token"])
def test_http_requires_per_run_token(token):
    with pytest.raises(PermissionError, match="会话"):
        handler(token=token)._check_mutation()


def test_http_allows_approved_same_origin_and_local_nonbrowser_clients():
    handler()._check_mutation()
    handler(host="localhost:8787", origin="http://localhost:8787")._check_mutation()
    handler(origin=None)._check_mutation()


@pytest.mark.parametrize("headers", [
    {"Content-Length": "-1"}, {"Content-Length": "99999"},
    {"Content-Length": "invalid"}, {"Transfer-Encoding": "chunked"},
])
def test_http_rejects_ambiguous_or_oversized_request_body(headers):
    request = handler()
    for key, value in headers.items():
        request.headers[key] = value
    request.rfile = io.BytesIO(b"{}")
    with pytest.raises(ValueError):
        request._body(limit=100)


def test_http_rejects_truncated_upload():
    request = handler()
    request.headers["Content-Length"] = "10"
    request.rfile = io.BytesIO(b"short")
    with pytest.raises(ValueError, match="未完成"):
        request._body(limit=100)


def test_http_errors_do_not_expose_internal_exception_details():
    request = handler()
    replies = []

    def fail():
        raise RuntimeError("private-path-and-secret-should-not-leak")

    request._dispatch = fail
    request._json = lambda value, status=200: replies.append((value, status))
    request._handle()
    assert replies[0][1] == 500
    assert "private-path-and-secret" not in json.dumps(replies)


@pytest.mark.parametrize(("mime", "ancestor_rule"), [
    ("text/html; charset=utf-8", "frame-ancestors 'none'"),
    ("application/pdf", "frame-ancestors 'self'"),
])
def test_http_security_headers_block_remote_embedding_but_allow_source_pdf(mime, ancestor_rule):
    request = handler()
    headers = {}
    request.send_response = lambda status: None
    request.send_header = lambda key, value: headers.update({key: value})
    request.end_headers = lambda: None
    request.wfile = io.BytesIO()
    request._reply(b"test", content_type=mime)
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert ancestor_rule in headers["Content-Security-Policy"]
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert "Access-Control-Allow-Origin" not in headers


def test_csv_export_blocks_formula_strings_without_changing_negative_amounts():
    result = server._csv({
        "company": "=HYPERLINK(evil)", "current_year": 2024, "previous_year": 2023,
        "rows": [{"label": "营业收入", "current_yuan": "-123.50", "previous_yuan": "100",
                  "change_pct": None, "delta_yuan": "-223.50", "status": "ready",
                  "current": {"filename": "\t=CMD(evil).pdf", "page": 5},
                  "previous": {"filename": "safe.pdf", "page": 5}, "notes": []}],
    })
    values = list(csv.reader(io.StringIO(result.lstrip("\ufeff"))))[1]
    assert values[0].startswith("'=HYPERLINK")
    assert values[4] == "-123.50"
    assert values[7] == "-223.50"
    assert values[9].startswith("'\t=CMD")


def test_server_state_and_page_output_use_native_tool_bridge(tmp_path, monkeypatch, report):
    monkeypatch.setattr(server, "model_status", lambda: {"configured": False, "provider": "deepseek"})
    application = server.AnnualReportApplication(tmp_path / "workspace")
    assert isinstance(application.tools, server.ReportToolBridge)
    dispatched = []
    permissions = []
    original_dispatch = application.tools.dispatch
    original_evaluate = application.tools.permission_checker.evaluate

    def dispatch(name, arguments):
        dispatched.append((name, deepcopy(arguments)))
        return original_dispatch(name, arguments)

    def evaluate(name, **kwargs):
        permissions.append((name, kwargs["is_read_only"]))
        return original_evaluate(name, **kwargs)

    monkeypatch.setattr(application.tools, "dispatch", dispatch)
    monkeypatch.setattr(application.tools.permission_checker, "evaluate", evaluate)
    state = application.state()
    assert state["comparison"] is None
    assert dispatched == [("annual_report_compare", {})]
    assert state["harness"]["permission_mode"] == "plan"
    application.store.reports[report["id"]] = deepcopy(report)
    result = application.tool_output("annual_report_page", {"report_id": report["id"], "page": 2})
    assert result["text"] == report["pages"][1]["text"]
    assert result["number"] == 2
    assert dispatched[-1] == ("annual_report_page", {"report_id": report["id"], "page": 2})
    assert permissions == [("annual_report_compare", True), ("annual_report_page", True)]


@pytest.mark.parametrize(("allowed", "requires_confirmation"), [(False, False), (True, True)])
def test_server_propagates_bridge_permission_denial_before_reading_source(
    tmp_path, monkeypatch, report, allowed, requires_confirmation,
):
    application = server.AnnualReportApplication(tmp_path / "workspace")
    monkeypatch.setattr(application.tools.permission_checker, "evaluate", lambda *args, **kwargs: SimpleNamespace(
        allowed=allowed, requires_confirmation=requires_confirmation,
    ))
    monkeypatch.setattr(application.store, "get", lambda report_id: pytest.fail("Denied tool read source data"))
    with pytest.raises(ValueError, match="权限不允许"):
        application.tool_output("annual_report_page", {"report_id": report["id"], "page": 2})


def test_health_does_not_wait_for_document_or_fingerprint_access(tmp_path, monkeypatch):
    application = server.AnnualReportApplication(tmp_path / "workspace")

    def forbidden(*args, **kwargs):
        pytest.fail("Health endpoint touched report state while an import could hold its lock")

    monkeypatch.setattr(application.store, "documents", forbidden)
    monkeypatch.setattr(application.store, "fingerprint", forbidden)
    monkeypatch.setattr(application, "state", forbidden)
    request = handler()
    request.server.application = application
    request.command = "GET"
    request.path = "/api/health"
    replies = []
    request._json = lambda value, status=200: replies.append((value, status))
    request._dispatch()
    assert replies == [({
        "app_version": "1.0.0",
        "workspace_id": hashlib.sha256(str(application.store.root).encode()).hexdigest()[:16],
    }, 200)]


@pytest.mark.parametrize(("reported_workspace", "version", "expected"), [
    ("expected-workspace", "1.0.0", True),
    ("another-workspace", "1.0.0", False),
    ("expected-workspace", "another-application", False),
])
def test_running_workspace_probe_uses_only_lightweight_health(
    monkeypatch, reported_workspace, version, expected,
):
    calls = []
    closed = []

    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1"
            assert port == 8787
            assert timeout <= 2

        def request(self, method, path):
            calls.append((method, path))

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda limit: json.dumps({
                "app_version": version, "workspace_id": reported_workspace,
            }).encode())

        def close(self):
            closed.append(True)

    monkeypatch.setattr(server, "HTTPConnection", Connection)
    assert server._same_workspace_running(0, "expected-workspace") is False
    assert calls == []
    assert server._same_workspace_running(8787, "expected-workspace") is expected
    assert calls == [("GET", "/api/health")]
    assert closed == [True]


@pytest.mark.parametrize("failure", ["timeout", "os_error", "http_error", "invalid_json", "non_object"])
def test_running_workspace_probe_failures_return_false_and_close_connection(monkeypatch, failure):
    closed = []

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path):
            assert method == "GET" and path == "/api/health"
            if failure == "timeout":
                raise TimeoutError("busy or unresponsive application")
            if failure == "os_error":
                raise OSError("connection unavailable")

        def getresponse(self):
            if failure == "http_error":
                return SimpleNamespace(status=503)
            data = b"not-json" if failure == "invalid_json" else b"[]"
            return SimpleNamespace(status=200, read=lambda limit: data)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(server, "HTTPConnection", Connection)
    assert server._same_workspace_running(8787, "expected-workspace") is False
    assert closed == [True]
