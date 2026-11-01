"""Source and wheel resources must work without writing beside installed code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openharness.annual_reports import __main__ as entrypoint
from openharness.annual_reports import paths, server


def demo(folder: Path, manifest: dict | None = None) -> Path:
    folder.mkdir(parents=True)
    (folder / "sources.json").write_text(json.dumps(manifest or {"reports": []}), encoding="utf-8")
    return folder


def installed_package(tmp_path: Path, monkeypatch) -> Path:
    package = tmp_path / "site-packages" / "openharness" / "annual_reports"
    package.mkdir(parents=True)
    monkeypatch.setattr(paths, "_package_dir", lambda: package)
    return package


def test_report_data_override_does_not_access_framework_or_package_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANNUAL_REPORT_DATA_DIR", "private-reports")
    monkeypatch.setattr(paths, "get_data_dir", lambda: pytest.fail("Explicit report directory was ignored"))
    assert paths.get_default_data_dir() == tmp_path / "private-reports"
    assert not (tmp_path / "private-reports").exists()


def test_report_data_defaults_to_framework_data_area(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNUAL_REPORT_DATA_DIR", " ")
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "runtime"))
    installed_package(tmp_path, monkeypatch)
    assert paths.get_default_data_dir() == tmp_path / "runtime" / "annual_reports"
    assert not (tmp_path / "site-packages" / "data").exists()


def test_source_resources_are_resolved_from_module_location_not_current_directory(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    package = root / "src" / "openharness" / "annual_reports"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    expected = demo(root / "data" / "annual_reports_demo")
    demo(package / "_demo")
    unrelated = tmp_path / "unrelated"
    demo(unrelated / "data" / "annual_reports_demo")
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(paths, "_package_dir", lambda: package)
    assert paths.resolve_demo_dir() == expected


def test_explicit_project_root_precedes_bundled_resources(tmp_path, monkeypatch):
    package = installed_package(tmp_path, monkeypatch)
    demo(package / "_demo")
    expected = demo(tmp_path / "selected-checkout" / "data" / "annual_reports_demo")
    assert paths.resolve_demo_dir(tmp_path / "selected-checkout") == expected


def test_unavailable_explicit_project_uses_bundle_without_searching_other_checkouts(tmp_path, monkeypatch):
    package = installed_package(tmp_path, monkeypatch)
    expected = demo(package / "_demo")
    monkeypatch.setattr(paths, "_source_project_root", lambda: pytest.fail("Explicit project was ignored"))
    assert paths.resolve_demo_dir(tmp_path / "missing-checkout") == expected


def test_installed_resources_work_outside_a_source_checkout(tmp_path, monkeypatch):
    package = installed_package(tmp_path, monkeypatch)
    expected = demo(package / "_demo")
    elsewhere = tmp_path / "outside-project"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert paths.resolve_demo_dir() == expected
    assert not (package / ".openharness").exists()


def test_missing_demo_does_not_prevent_local_workspace_startup(tmp_path, monkeypatch):
    installed_package(tmp_path, monkeypatch)
    application = server.AnnualReportApplication(tmp_path / "private-workspace")
    assert application.store.documents() == []
    with pytest.raises(ValueError, match="公开示例资源缺失"):
        application.load_demo()


def test_demo_import_and_source_information_use_the_same_bundled_manifest(tmp_path, monkeypatch):
    package = installed_package(tmp_path, monkeypatch)
    payload = b"test PDF bytes; extraction is covered separately"
    manifest = {"reports": [{
        "file": "sample.pdf", "display_name": "公开示例.pdf", "url": "https://example.com/sample.pdf",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }]}
    folder = demo(package / "_demo", manifest)
    (folder / "sample.pdf").write_bytes(payload)
    application = server.AnnualReportApplication(tmp_path / "workspace")
    imported = []
    monkeypatch.setattr(application.store, "add_pdf", lambda *args: imported.append(args))
    application.load_demo()
    assert imported == [(payload, "公开示例.pdf", "https://example.com/sample.pdf")]

    request = server.ReportHandler.__new__(server.ReportHandler)
    request.server = SimpleNamespace(server_address=("127.0.0.1", 8787), application=application)
    request.headers = {"Host": "127.0.0.1:8787"}
    request.path, request.command = "/api/demo-info", "GET"
    replies = []
    request._json = lambda value, status=200: replies.append((value, status))
    request._dispatch()
    assert replies == [(manifest, 200)]


@pytest.mark.parametrize("host", ["localhost", "::1", "192.168.1.2", "example.com", "", None])
def test_invalid_bind_is_rejected_before_creating_a_workspace(monkeypatch, host):
    monkeypatch.setattr(server, "AnnualReportApplication", lambda *args: pytest.fail("Invalid bind created data"))
    monkeypatch.setattr(server, "get_default_data_dir", lambda: pytest.fail("Invalid bind read user configuration"))
    with pytest.raises(ValueError, match="监听地址"):
        server.serve(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_explicit_bind_preserves_loopback_host_and_origin_validation(host):
    request = server.ReportHandler.__new__(server.ReportHandler)
    request.server = SimpleNamespace(server_address=(host, 8787), application=SimpleNamespace(token="token"))
    request.headers = {"Host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:8787", "X-Annual-Token": "token"}
    request._check_mutation()
    request.headers["Host"] = "192.168.1.2:8787"
    with pytest.raises(PermissionError, match="本机"):
        request._check_mutation()
    request.headers["Host"] = "127.0.0.1:8787"
    request.headers["Origin"] = "http://example.com"
    with pytest.raises(PermissionError, match="来源"):
        request._check_mutation()


@pytest.mark.parametrize("requested_host", [None, "0.0.0.0"])
def test_server_uses_writable_data_and_requested_bind(tmp_path, monkeypatch, requested_host):
    monkeypatch.delenv("ANNUAL_REPORT_DATA_DIR", raising=False)
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "runtime"))
    directories, listeners, closed = [], [], []
    monkeypatch.setattr(server, "AnnualReportApplication", lambda folder: directories.append(folder))

    class Listener:
        def __init__(self, address, application):
            self.server_address = address
            listeners.append(address)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            closed.append(True)

    monkeypatch.setattr(server, "ReportHTTPServer", Listener)
    kwargs = {"host": requested_host} if requested_host is not None else {}
    server.serve(port=8787, **kwargs)
    assert directories == [tmp_path / "runtime" / "annual_reports"]
    assert listeners == [(requested_host or "127.0.0.1", 8787)]
    assert closed == [True]


def test_module_cli_accepts_explicit_container_bind(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(entrypoint, "serve", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr("sys.argv", ["reports", "--host", "0.0.0.0", "--data-dir", str(tmp_path)])
    entrypoint.main()
    assert calls == [((8787, tmp_path, False), {"host": "0.0.0.0"})]


def test_module_cli_rejects_other_interfaces_before_serving(monkeypatch):
    monkeypatch.setattr(entrypoint, "serve", lambda *args, **kwargs: pytest.fail("Invalid CLI bind was served"))
    monkeypatch.setattr("sys.argv", ["reports", "--host", "192.168.1.2"])
    with pytest.raises(SystemExit) as error:
        entrypoint.main()
    assert error.value.code == 2
