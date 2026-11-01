"""Native OpenHarness tool bridge for the annual-report application.

This adapter uses the framework's actual tool registry, parameter models,
permission checker, execution context and result contract. It deliberately
registers only three read-only report tools. It does not create an autonomous
model loop, load the default tool set, or accept filesystem paths or commands.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from openharness.config.settings import PermissionSettings
from openharness.permissions.checker import PermissionChecker
from openharness.permissions.modes import PermissionMode
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult

from .analysis import answer_question

if TYPE_CHECKING:
    from .store import ReportStore


class ReportSearchInput(BaseModel):
    """Search only the reports explicitly imported into the current workspace."""

    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=2000, description="关于已导入年报的问题")

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入年报问题。")
        return value


class ReportPageInput(BaseModel):
    """Address a known document by its content ID and physical PDF page."""

    model_config = ConfigDict(extra="forbid", strict=True)
    report_id: str = Field(pattern=r"^[0-9a-f]{20}$", description="已导入报告的 20 位内容标识")
    page: int = Field(ge=1, le=500, description="从 PDF 第一页起计数的物理页码")


class ReportCompareInput(BaseModel):
    """Comparison always uses the existing workspace; no path arguments."""

    model_config = ConfigDict(extra="forbid", strict=True)


def _sources(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[tuple] = set()
    for item in items:
        page = item.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            continue
        source = {
            "report_id": str(item.get("report_id", "")),
            "filename": str(item.get("filename", "")),
            "page": page,
            "evidence": str(item.get("evidence", ""))[:800],
        }
        signature = (source["report_id"], source["page"], source["evidence"])
        if signature not in seen:
            seen.add(signature)
            result.append(source)
    return result


def _result(payload: dict, sources: list[dict] | None = None, *, error: bool = False) -> ToolResult:
    return ToolResult(
        output=json.dumps(payload, ensure_ascii=False, allow_nan=False),
        is_error=error,
        metadata={"source_boundary": "imported_reports_only", "sources": _sources(sources or [])},
    )


class _ReadOnlyReportTool(BaseTool):
    def __init__(self, store: ReportStore) -> None:
        self.store = store

    def is_read_only(self, arguments: BaseModel) -> bool:
        del arguments
        return True


class AnnualReportSearchTool(_ReadOnlyReportTool):
    """Expose deterministic Q&A and local retrieval as a native framework tool."""

    name = "annual_report_search"
    description = "查询已导入年报的指标或原文，保留来源和待核对状态；不会联网。"
    input_model = ReportSearchInput

    async def execute(
        self, arguments: ReportSearchInput, context: ToolExecutionContext,
    ) -> ToolResult:
        del context
        payload = answer_question(self.store.documents(), arguments.question)
        return _result(payload, payload.get("citations", []))


class AnnualReportPageTool(_ReadOnlyReportTool):
    """Read an indexed source page, never an arbitrary filesystem location."""

    name = "annual_report_page"
    description = "读取已导入报告的指定 PDF 物理页，返回原文和来源；不能读取任意路径。"
    input_model = ReportPageInput

    async def execute(
        self, arguments: ReportPageInput, context: ToolExecutionContext,
    ) -> ToolResult:
        del context
        try:
            report = self.store.get(arguments.report_id)
        except ValueError:
            return _result({"error": "未找到这份已导入年报，请重新选择资料。"}, error=True)
        pages = report.get("pages", [])
        if arguments.page > len(pages):
            return _result({"error": "PDF 物理页码超出这份年报的范围。"}, error=True)
        page = pages[arguments.page - 1]
        if page.get("number") != arguments.page:
            return _result({"error": "报告页码索引不一致，请重新导入这份年报。"}, error=True)
        payload = {
            "number": arguments.page, "text": str(page.get("text", "")),
            "filename": report.get("filename", ""), "report_id": report.get("id", ""),
        }
        return _result(payload, [{
            "report_id": payload["report_id"], "filename": payload["filename"],
            "page": arguments.page, "evidence": payload["text"],
        }])


class AnnualReportCompareTool(_ReadOnlyReportTool):
    """Return the reviewed comparison already produced by the store."""

    name = "annual_report_compare"
    description = "读取当前工作区的年报比较结果，候选值不参与正式计算；不修改确认状态。"
    input_model = ReportCompareInput

    async def execute(
        self, arguments: ReportCompareInput, context: ToolExecutionContext,
    ) -> ToolResult:
        del arguments, context
        state = self.store.state()
        comparison = state.get("comparison")
        error = str(state.get("comparison_error") or "")
        if error:
            return _result({"error": error, "comparison": None, "comparison_error": error}, error=True)
        citations = []
        for row in (comparison or {}).get("rows", []):
            citations.extend(metric for metric in (row.get("current"), row.get("previous")) if metric)
        return _result({"comparison": comparison, "comparison_error": ""}, citations)


class ReportToolBridge:
    """Execute a restricted native tool set from a threaded local HTTP server."""

    def __init__(self, store: ReportStore) -> None:
        self.store = store
        self.registry = ToolRegistry()
        for tool in (AnnualReportSearchTool(store), AnnualReportPageTool(store), AnnualReportCompareTool(store)):
            self.registry.register(tool)
        self.permission_settings = PermissionSettings(mode=PermissionMode.PLAN)
        self.permission_checker = PermissionChecker(self.permission_settings)

    @property
    def tools_schema(self) -> list[dict[str, Any]]:
        return self.registry.to_api_schema()

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.registry.list_tools()]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        """Validate, authorize, and execute through the framework contracts."""
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _result({"error": "工具请求格式无效。"}, error=True)
        tool = self.registry.get(name)
        if tool is None:
            return _result({"error": "工具未注册；仅支持年报查询、原文页和指标比较。"}, error=True)
        try:
            validated = tool.input_model.model_validate(arguments)
        except ValidationError:
            # Do not echo invalid input: it could itself contain secret values.
            return _result({"error": "工具参数无效，请检查问题、报告编号和 PDF 物理页码。"}, error=True)
        try:
            decision = self.permission_checker.evaluate(tool.name, is_read_only=tool.is_read_only(validated))
            permission = {
                "allowed": decision.allowed, "requires_confirmation": decision.requires_confirmation,
                "mode": PermissionMode.PLAN.value,
            }
            if not decision.allowed or decision.requires_confirmation:
                result = _result({"error": "当前只读年报权限不允许执行这个工具。"}, error=True)
                return ToolResult(result.output, True, {**result.metadata, "permission": permission})
            context = ToolExecutionContext(
                cwd=self.store.root,
                metadata={"application": "annual_reports", "permission_mode": PermissionMode.PLAN.value,
                          "source_boundary": "imported_reports_only"},
            )
            result = await tool.execute(validated, context)
            return ToolResult(
                result.output, result.is_error,
                {**result.metadata, "permission": permission, "tool": tool.name},
            )
        except Exception:
            # Public errors must not expose stack traces, local paths, credentials
            # or document contents from an unexpected implementation failure.
            return _result({"error": "年报工具执行未完成，请刷新后重试。"}, error=True)

    def dispatch(self, name: str, arguments: dict) -> dict:
        """Synchronous adapter; call from request threads without an event loop."""
        try:
            result = asyncio.run(self.execute(name, arguments))
            payload = json.loads(result.output)
            if not isinstance(payload, dict):
                raise ValueError("invalid tool result")
        except Exception:
            return {
                "tool": name if isinstance(name, str) else "",
                "is_error": True, "output": {"error": "年报工具执行未完成，请稍后重试。"},
                "metadata": {"source_boundary": "imported_reports_only", "sources": []},
            }
        return {"tool": name, "is_error": result.is_error, "output": payload, "metadata": result.metadata}
