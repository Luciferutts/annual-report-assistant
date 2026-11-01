"""Native registry/schema/permission execution and imported-document boundaries."""

import asyncio
import json
from pathlib import Path

import pytest

from openharness.annual_reports.harness import ReportToolBridge
from openharness.permissions.checker import PermissionDecision
from openharness.permissions.modes import PermissionMode
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


REPORT_ID = "a" * 20


class MemoryStore:
    def __init__(self, root: Path):
        self.root = root
        self.document_calls = 0
        self.get_calls = []
        self.report = {
            "id": REPORT_ID, "filename": "公开年报.pdf", "year": 2024,
            "company": "示例股份有限公司", "currency": "CNY", "metrics": [],
            "pages": [{"number": 1, "text": "营业收入原文。"}, {"number": 2, "text": "风险披露原文。"}],
        }
        self.comparison = {"current_year": 2024, "previous_year": 2023, "rows": []}

    def documents(self):
        self.document_calls += 1
        return [self.report]

    def get(self, report_id):
        self.get_calls.append(report_id)
        if report_id != REPORT_ID:
            raise ValueError("not imported")
        return self.report

    def state(self):
        return {"comparison": self.comparison, "comparison_error": ""}


@pytest.fixture
def bridge(tmp_path):
    return ReportToolBridge(MemoryStore(tmp_path))


def test_registry_contains_only_three_native_tools_with_strict_schemas(bridge):
    assert bridge.tool_names == ["annual_report_search", "annual_report_page", "annual_report_compare"]
    assert all(isinstance(tool, BaseTool) for tool in bridge.registry.list_tools())
    schemas = {schema["name"]: schema["input_schema"] for schema in bridge.tools_schema}
    assert schemas["annual_report_search"]["required"] == ["question"]
    assert schemas["annual_report_page"]["required"] == ["report_id", "page"]
    assert schemas["annual_report_page"]["properties"]["page"]["minimum"] == 1
    assert all(schema["additionalProperties"] is False for schema in schemas.values())
    assert bridge.permission_settings.mode == PermissionMode.PLAN


def test_local_search_returns_standard_framework_result(bridge):
    result = asyncio.run(bridge.execute("annual_report_search", {"question": "我该怎么使用你"}))
    assert isinstance(result, ToolResult)
    assert not result.is_error
    assert json.loads(result.output)["mode"] == "local"
    assert result.metadata["permission"] == {"allowed": True, "requires_confirmation": False, "mode": "plan"}
    assert result.metadata["source_boundary"] == "imported_reports_only"


def test_page_dispatch_returns_exact_imported_page_and_source_metadata(bridge):
    result = bridge.dispatch("annual_report_page", {"report_id": REPORT_ID, "page": 2})
    assert result["is_error"] is False
    assert result["output"] == {
        "number": 2, "text": "风险披露原文。", "filename": "公开年报.pdf", "report_id": REPORT_ID,
    }
    assert result["metadata"]["sources"][0]["page"] == 2
    assert result["metadata"]["sources"][0]["evidence"] == "风险披露原文。"


@pytest.mark.parametrize("arguments", [
    {"report_id": "../../etc/passwd", "page": 1},
    {"report_id": REPORT_ID, "page": 0},
    {"report_id": REPORT_ID, "page": 501},
    {"report_id": REPORT_ID, "page": True},
    {"report_id": REPORT_ID, "page": "1"},
    {"report_id": REPORT_ID, "page": 1, "path": "/etc/passwd"},
])
def test_invalid_page_arguments_are_rejected_before_store_access(bridge, arguments):
    result = bridge.dispatch("annual_report_page", arguments)
    assert result["is_error"] is True
    assert "参数无效" in result["output"]["error"]
    assert bridge.store.get_calls == []


@pytest.mark.parametrize("arguments", [{"question": " "}, {"question": "a" * 2001}, {"question": 3}])
def test_invalid_questions_are_rejected_before_reading_reports(bridge, arguments):
    assert bridge.dispatch("annual_report_search", arguments)["is_error"] is True
    assert bridge.store.document_calls == 0


def test_unknown_imported_id_and_out_of_range_page_are_actionable_errors(bridge):
    unknown = bridge.dispatch("annual_report_page", {"report_id": "b" * 20, "page": 1})
    assert unknown["is_error"] is True
    assert "未找到这份已导入年报" in unknown["output"]["error"]
    overflow = bridge.dispatch("annual_report_page", {"report_id": REPORT_ID, "page": 3})
    assert overflow["is_error"] is True
    assert "超出" in overflow["output"]["error"]


def test_unknown_shell_tool_is_not_dispatched(bridge, monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("No shell or process may run")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = bridge.dispatch("bash", {"command": "cat /etc/passwd"})
    assert result["is_error"] is True
    assert "未注册" in result["output"]["error"]
    assert bridge.store.document_calls == 0
    assert bridge.store.get_calls == []


def test_registered_tools_do_not_launch_processes_or_open_network_connections(bridge, monkeypatch):
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("Report tools must stay local and read-only")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    requests = [
        ("annual_report_search", {"question": "风险披露有哪些"}),
        ("annual_report_page", {"report_id": REPORT_ID, "page": 1}),
        ("annual_report_compare", {}),
    ]
    for name, arguments in requests:
        assert bridge.dispatch(name, arguments)["is_error"] is False


def test_native_permission_checker_is_called_before_execution(bridge, monkeypatch):
    calls = []
    original = bridge.permission_checker.evaluate

    def spy(tool_name, **kwargs):
        calls.append((tool_name, kwargs))
        return original(tool_name, **kwargs)

    monkeypatch.setattr(bridge.permission_checker, "evaluate", spy)
    result = bridge.dispatch("annual_report_page", {"report_id": REPORT_ID, "page": 1})
    assert not result["is_error"]
    assert calls == [("annual_report_page", {"is_read_only": True})]


@pytest.mark.parametrize("decision", [
    PermissionDecision(allowed=False, reason="test denial"),
    PermissionDecision(allowed=True, requires_confirmation=True, reason="test review"),
])
def test_permission_decision_can_prevent_actual_store_read(bridge, monkeypatch, decision):
    monkeypatch.setattr(bridge.permission_checker, "evaluate", lambda *args, **kwargs: decision)
    result = bridge.dispatch("annual_report_search", {"question": "营业收入"})
    assert result["is_error"] is True
    assert bridge.store.document_calls == 0
    assert result["metadata"]["permission"]["allowed"] is decision.allowed


def test_native_plan_mode_blocks_a_mutating_tool_before_execute(bridge):
    class MutatingTool(BaseTool):
        name = "test_mutation"
        description = "test only"
        input_model = bridge.registry.get("annual_report_compare").input_model

        async def execute(self, arguments, context):
            raise AssertionError("Plan permission must block mutation")

    bridge.registry.register(MutatingTool())
    result = bridge.dispatch("test_mutation", {})
    assert result["is_error"] is True
    assert result["metadata"]["permission"]["allowed"] is False


def test_tool_receives_real_execution_context(bridge, monkeypatch):
    contexts = []
    tool = bridge.registry.get("annual_report_compare")
    original = tool.execute

    async def spy(arguments, context):
        contexts.append(context)
        return await original(arguments, context)

    monkeypatch.setattr(tool, "execute", spy)
    result = bridge.dispatch("annual_report_compare", {})
    assert not result["is_error"]
    assert result["output"]["comparison"] == bridge.store.comparison
    assert isinstance(contexts[0], ToolExecutionContext)
    assert contexts[0].cwd == bridge.store.root
    assert contexts[0].metadata["source_boundary"] == "imported_reports_only"


def test_unexpected_failure_does_not_expose_exception_or_paths(bridge, monkeypatch):
    def broken():
        raise RuntimeError("secret-api-key-123 /private/user/.ssh/key")

    monkeypatch.setattr(bridge.store, "documents", broken)
    result = bridge.dispatch("annual_report_search", {"question": "营业收入"})
    assert result["is_error"] is True
    output = json.dumps(result, ensure_ascii=False)
    assert "secret-api-key" not in output
    assert "/private/" not in output
    assert "RuntimeError" not in output
