# GitHub 发布说明

此目录是可独立安装的源代码仓库。OpenHarness 核心和年报应用在同一个项目内，不需要依赖原电脑上的其他项目文件夹。

## 发布前检查

1. 保留 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 和公开报告的来源记录。
2. 提交 `pyproject.toml`、`uv.lock`、前端的 `package-lock.json`，使依赖范围可检查和复现。
3. 不提交 `.env`、凭据文件、本地配置、上传资料、会话、缓存、`.venv`、`node_modules` 或运行数据目录。
4. `.env.example` 只能包含说明和空的占位值；本地程序不会自动读取 `.env`。
5. 检查截图和示例底稿只包含拟公开的资料。本仓库演示资料为公开历史年报；它们不自动适用代码的 MIT 许可。
6. 原项目中需要外部真实服务、含本机工作区或疑似密钥默认值的四份手工测试没有纳入发布包；不要从旧目录直接复制回来。
7. 发布包只启用只读权限的 CI。未启用原项目的定时 autopilot 写仓库、推送和 Pages 部署工作流。

不应把配置保存成功、代码测试通过或来源编号合法等同于云端可用、全面安全或所有分析结论正确。

## 从干净目录验证

Python 推荐使用 3.12：

```sh
uv sync --locked --extra reports --extra dev
uv run --locked --extra reports --extra dev pytest tests/test_annual_reports -q
uv run --locked --extra reports --extra dev ruff check src/openharness/annual_reports tests/test_annual_reports
uv run --locked --extra reports python scripts/evaluate_annual_reports.py
uv run --locked --extra reports annual-report-assistant --open
```

先对运行中的应用验收内置公开示例：

```sh
uv run --locked --extra reports python scripts/check_reports_http.py --url http://127.0.0.1:8787
```

上面命令默认不调用模型。测试模型外发时，显式添加 `--live-model`；真实解读需要模型密钥、账户可用和相应调用费用。

全框架测试包含更多运行环境要求。离线验证时应隔离 `OPENHARNESS_CONFIG_DIR`、`OPENHARNESS_DATA_DIR` 和 `OPENHARNESS_LOGS_DIR`，不要让测试读取个人真实配置。当前 GitHub CI 专注年报业务测试。

## 验证 wheel

```sh
uv build --wheel
```

在仓库以外的临时虚拟环境安装生成的 wheel，检查：

- `annual-report-assistant --help` 与 `oh reports --help` 可执行。
- 从另一个工作目录启动时，静态页面和公开演示 PDF 仍然可用。
- 默认工作数据写入用户数据目录，而非安装目录。
- 启用 `--data-dir` 或 `ANNUAL_REPORT_DATA_DIR` 时使用指定的可写目录。

仅在源码根目录测试通过，无法证明 wheel 的静态文件和示例资源已经完整打包。

## 本地 Git 仓库与上传

在本目录打开终端，确认 `.gitignore` 与拟提交内容后执行：

```sh
git init -b main
git add .
git diff --cached --stat
git diff --cached --name-only
git commit -m "Initial annual report assistant release"
```

在 GitHub 创建一个空仓库后，将下面的用户名替换为自己的账户：

```sh
git remote add origin https://github.com/<你的用户名>/annual-report-assistant.git
git push -u origin main
```

这些是操作者执行的发布步骤。打包和本地验证本身不会创建远程仓库、上传代码或公开资料。不要在远程 URL 中放入密码或访问令牌。

## 可选通用终端前端

年报网页不需要 Node。通用 OpenHarness 终端前端的依赖由以下命令安装：

```sh
cd frontend/terminal
npm ci
```

保留前端源码和锁定文件，不提交生成的 `node_modules`。
