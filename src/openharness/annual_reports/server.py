"""Local annual-report workspace with loopback defaults and explicit egress."""

from __future__ import annotations

import csv
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection, HTTPException
import io
import json
from pathlib import Path
import re
import secrets
import socket
import threading
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser

from .analysis import render_markdown
from .harness import ReportToolBridge
from .model import PreviewManager, model_status
from .paths import get_default_data_dir, resolve_demo_dir, validate_bind_host
from .rendering import PageRenderer
from .store import MAX_UPLOAD, ReportStore

STATIC = Path(__file__).parent / "static"
PRIVACY = {
    "local_extraction": True, "automatic_upload_to_model": False,
    "model_requires_preview_and_approval": True, "telemetry": False,
    "local_retention": "上传的 PDF、提取结果和复核记录仅保存在本项目工作区；可从资料库删除。",
    "remote_notice": "只有确认发送后，预览中显示的问题、已核对数据与原文节选才会发往 DeepSeek。",
    "scope": "仅处理主动导入的 PDF；不会扫描其他文件夹或执行模型命令。",
}


class AnnualReportApplication:
    def __init__(self, data_dir: Path, project_root: Path | None = None) -> None:
        self.store = ReportStore(data_dir)
        self.tools = ReportToolBridge(self.store)
        self.page_renderer = PageRenderer(self.store)
        self.project_root = project_root
        self.token = secrets.token_urlsafe(32)
        self.previews = PreviewManager(self.store.fingerprint)
        self.model_lock = threading.Lock()

    @property
    def demo_dir(self) -> Path:
        return resolve_demo_dir(self.project_root)

    def state(self) -> dict:
        documents = self.store.documents()
        metadata = [{key: value for key, value in report.items() if key not in {"pages", "audit"}}
                    for report in documents]
        compared = self.tools.dispatch("annual_report_compare", {})["output"]
        return {
            "reports": metadata, "comparison": compared.get("comparison"),
            "comparison_error": compared.get("comparison_error") or compared.get("error", ""),
            "model": model_status(), "privacy": PRIVACY,
            "harness": {"framework": "OpenHarness", "tools": self.tools.tool_names,
                        "permission_mode": "plan", "autonomous_model_loop": False},
            "csrf_token": self.token, "app_version": "1.0.0",
            "workspace_revision": self.store.fingerprint(),
            "workspace_id": hashlib.sha256(str(self.store.root).encode()).hexdigest()[:16],
        }

    def tool_output(self, name: str, arguments: dict) -> dict:
        result = self.tools.dispatch(name, arguments)
        if result["is_error"]:
            raise ValueError(result["output"].get("error", "年报工具执行未完成。"))
        return result["output"]

    def load_demo(self) -> None:
        folder = self.demo_dir
        manifest_path = folder / "sources.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sources = manifest["reports"]
        with self.store.lock:
            if self.store.reports:
                raise ValueError("请先移除当前资料，再载入两份公开年报示例。")
            try:
                for source in sources:
                    filename = source["file"]
                    if Path(filename).name != filename:
                        raise ValueError("示例文件名不正确。")
                    path = folder / filename
                    if not path.is_file():
                        raise ValueError("公开示例 PDF 缺失，请上传自己的年报。")
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != source["sha256"]:
                        raise ValueError("示例 PDF 与来源记录不一致，请恢复原文件后重试。")
                    self.store.add_pdf(data, source["display_name"], source["url"])
            except Exception:
                for report in self.store.documents():
                    self.store.delete(report["id"])
                raise
        self.previews.clear()


def _csv(comparison: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["公司", "指标", "本期年度", "上期年度", "本期金额(人民币元)",
                     "上期金额(人民币元)", "同比(%)", "差额(人民币元)", "状态",
                     "本期来源", "本期PDF页", "上期来源", "上期PDF页", "说明"])
    for row in comparison.get("rows", []):
        current, previous = row.get("current") or {}, row.get("previous") or {}
        values = [comparison.get("company"), row.get("label"), comparison.get("current_year"),
                  comparison.get("previous_year"), row.get("current_yuan"), row.get("previous_yuan"),
                  row.get("change_pct"), row.get("delta_yuan"),
                  {"ready": "已核对", "needs_review": "待核对", "missing": "缺少数据"}.get(row.get("status"), ""),
                  current.get("filename"), current.get("page"), previous.get("filename"), previous.get("page"),
                  "；".join(row.get("notes", []))]
        # Spreadsheet formula injection prevention applies to all human-controlled strings.
        writer.writerow([("'" + str(value)) if isinstance(value, str)
                         and value.lstrip()[:1] in {"=", "+", "-", "@"}
                         and not re.fullmatch(r"-?\d+(?:\.\d+)?", value)
                         else "" if value is None else value for value in values])
    return "\ufeff" + output.getvalue()


class ReportHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], application: AnnualReportApplication) -> None:
        self.application = application
        super().__init__(address, ReportHandler)


class ReportHandler(BaseHTTPRequestHandler):
    server_version = "AnnualReportAssistant/1.0"

    @property
    def app(self) -> AnnualReportApplication:
        return self.server.application  # type: ignore[attr-defined]

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(90)

    def log_message(self, _format: str, *args: object) -> None:
        # User questions, filenames and model request content must not enter HTTP logs.
        pass

    def _reply(self, body: bytes, content_type: str = "application/json; charset=utf-8",
               status: int = 200, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        ancestors = "'self'" if content_type == "application/pdf" else "'none'"
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'self'; "
                         f"base-uri 'none'; form-action 'self'; frame-ancestors {ancestors}")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, value: dict, status: int = 200) -> None:
        self._reply(json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), status=status)

    def _check_host(self) -> None:
        port = self.server.server_address[1]
        if self.headers.get("Host", "").lower() not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            raise PermissionError("仅允许从本机地址访问。")

    def _check_mutation(self) -> None:
        self._check_host()
        port = self.server.server_address[1]
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            raise PermissionError("请求来源不匹配，请从本机应用页面操作。")
        if not secrets.compare_digest(self.headers.get("X-Annual-Token", ""), self.app.token):
            raise PermissionError("页面会话已变化，请刷新后重试。")

    def _body(self, limit: int = 16_384) -> bytes:
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("不支持分块上传，请从应用页面选择 PDF。")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("请求长度不正确。") from None
        if length < 0 or length > limit:
            raise ValueError("上传或请求内容超过大小限制。")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("文件上传未完成，请重新选择文件。")
        return body

    def _json_body(self) -> dict:
        raw = self._body()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("请求内容格式不正确。") from None
        if not isinstance(value, dict):
            raise ValueError("请求内容应为对象。")
        return value

    @staticmethod
    def _question(body: dict) -> str:
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("请先输入你想核对的问题。")
        if len(question) > 2000:
            raise ValueError("问题请控制在 2000 字以内，便于定位具体年报依据。")
        return question.strip()

    def _dispatch(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)
        if self.command == "GET":
            self._check_host()
            if path in {"/", "/index.html"}:
                self._reply((STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path in {"/static/app.js", "/static/style.css"}:
                mime = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
                self._reply((STATIC / Path(path).name).read_bytes(), mime)
            elif path == "/api/state":
                self._json(self.app.state())
            elif path == "/api/health":
                # This must remain responsive while PDF import holds the store lock.
                self._json({
                    "app_version": "1.0.0",
                    "workspace_id": hashlib.sha256(str(self.app.store.root).encode()).hexdigest()[:16],
                })
            elif path == "/api/demo-info":
                self._json(json.loads((self.app.demo_dir / "sources.json").read_text(encoding="utf-8")))
            elif path == "/api/export":
                state = self.app.state()
                comparison = state.get("comparison")
                if not comparison:
                    raise ValueError(state.get("comparison_error") or "请先导入年报并检查比较结果。")
                name = "年报对比底稿-" + str(comparison.get("current_year", ""))
                if query.get("format", ["markdown"])[0] == "csv":
                    self._reply(_csv(comparison).encode(), "text/csv; charset=utf-8", filename=name + ".csv")
                else:
                    memo = render_markdown(comparison, self.app.store.documents())
                    self._reply(memo.encode(), "text/markdown; charset=utf-8", filename=name + ".md")
            elif match := re.fullmatch(r"/api/reports/([0-9a-f]{20})/page/(\d+)", path):
                page = int(match[2])
                self._json(self.app.tool_output("annual_report_page", {"report_id": match[1], "page": page}))
            elif match := re.fullmatch(r"/api/reports/([0-9a-f]{20})/image/(\d+)", path):
                self.app.tool_output("annual_report_page", {"report_id": match[1], "page": int(match[2])})
                self._reply(self.app.page_renderer.render(match[1], int(match[2])), "image/png")
            elif match := re.fullmatch(r"/api/reports/([0-9a-f]{20})/pdf", path):
                self.app.tool_output("annual_report_page", {"report_id": match[1], "page": 1})
                report = self.app.store.get(match[1])
                self._reply((self.app.store.root / f"{report['id']}.pdf").read_bytes(), "application/pdf")
            else:
                self._json({"error": "未找到这个页面。"}, 404)
            return

        self._check_mutation()
        if self.command == "POST" and path == "/api/upload":
            filename = query.get("filename", [""])[0]
            self.app.store.add_pdf(self._body(MAX_UPLOAD), filename)
            self.app.previews.clear()
            self._json(self.app.state())
        elif self.command == "POST" and path == "/api/demo":
            self._json_body()
            self.app.load_demo()
            self._json(self.app.state())
        elif self.command == "PATCH" and (match := re.fullmatch(r"/api/reports/([0-9a-f]{20})/metrics", path)):
            self.app.store.confirm_metric(match[1], self._json_body())
            self.app.previews.clear()
            self._json(self.app.state())
        elif self.command == "DELETE" and (match := re.fullmatch(r"/api/reports/([0-9a-f]{20})", path)):
            self.app.store.delete(match[1])
            self.app.previews.clear()
            self.app.page_renderer.clear()
            self._json(self.app.state())
        elif self.command == "POST" and path == "/api/ask":
            question = self._question(self._json_body())
            self._json(self.app.tool_output("annual_report_search", {"question": question}))
        elif self.command == "POST" and path == "/api/model-preview":
            question = self._question(self._json_body())
            with self.app.store.lock:
                reports = self.app.store.documents()
                comparison = self.app.tools.dispatch("annual_report_compare", {})["output"].get("comparison")
                local = self.app.tool_output("annual_report_search", {"question": question})
                preview = self.app.previews.create(question, reports, comparison, local)
            self._json(preview)
        elif self.command == "POST" and path == "/api/model-send":
            body = self._json_body()
            if not self.app.model_lock.acquire(blocking=False):
                raise ValueError("已有解读请求正在处理，请稍候。")
            try:
                preview_id = body.get("preview_id")
                if not isinstance(preview_id, str) or len(preview_id) > 100:
                    raise ValueError("请先预览需要发送的内容。")
                self._json(self.app.previews.send(preview_id, body.get("approved")))
            finally:
                self.app.model_lock.release()
        else:
            self._json({"error": "未找到这个操作。"}, 404)

    def _handle(self) -> None:
        try:
            self._dispatch()
        except PermissionError as exc:
            self._json({"error": str(exc)}, 403)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except (socket.timeout, TimeoutError):
            self._json({"error": "处理超时，请稍后重试或换用体积较小的年报。"}, 408)
        except Exception:
            self._json({"error": "处理未完成。请检查年报是否为可复制文字的正式年度报告，并重试。"}, 500)

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_DELETE = _handle


def _same_workspace_running(port: int, workspace_id: str) -> bool:
    if not port:
        return False
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        if response.status != 200:
            return False
        data = json.loads(response.read(2 * 1024 * 1024))
        return isinstance(data, dict) and data.get("app_version") == "1.0.0" and data.get("workspace_id") == workspace_id
    except (OSError, ValueError, TimeoutError, HTTPException):
        return False
    finally:
        connection.close()


def serve(port: int = 8787, data_dir: Path | None = None, open_browser: bool = False,
          *, host: str = "127.0.0.1") -> None:
    host = validate_bind_host(host)
    if not 0 <= port <= 65535:
        raise ValueError("端口应在 0 到 65535 之间。")
    application = AnnualReportApplication(data_dir if data_dir is not None else get_default_data_dir())
    try:
        server = ReportHTTPServer((host, port), application)
    except OSError:
        workspace_id = hashlib.sha256(str(application.store.root).encode()).hexdigest()[:16]
        if _same_workspace_running(port, workspace_id):
            url = f"http://127.0.0.1:{port}"
            print(f"年报分析助手已在运行：{url}", flush=True)
            if open_browser:
                webbrowser.open(url)
            return
        # Another application's port must not prevent this workspace from opening.
        server = ReportHTTPServer((host, 0), application)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"年报分析助手已启动：{url}", flush=True)
    print("默认本地处理；模型发送需要逐次预览确认。关闭此窗口可停止服务。", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
