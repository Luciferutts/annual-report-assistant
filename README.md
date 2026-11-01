# 年报分析助手 · Annual Report Assistant

面向中文上市公司年报的财务分析助手，基于 OpenHarness 构建，覆盖从 PDF 导入、指标提取、原文核对到跨年比较与底稿导出的完整流程。

项目关注年报分析中耗费精力的数据准备工作：关键数字分散在不同页面，金额单位和统计口径存在差异，跨年数据还可能发生调整。通过保留来源证据、设置人工复核环节和明确计算规则，将这些信息整理成可检查、可追溯的分析底稿。

## 核心功能

- **财务指标提取**：从文字版 PDF 中提取营业收入、归母净利润、扣非归母净利润、经营现金流净额、总资产与归母净资产。
- **原文溯源与复核**：查看指标对应的原文页，核对年度、金额、单位和合并口径；确认后进入正式比较。
- **跨年财务对比**：使用 Decimal 计算差额与同比，处理缺失值、零或负数基数，并提示可比期数据差异。
- **本地问答与检索**：回答支持范围内的指标问题，为经营原因、风险和细分口径问题提供原文线索。
- **可选模型解读**：接入 DeepSeek，先预览实际发送内容，再由用户确认外发。
- **底稿导出**：生成包含数据来源与核对状态的 Markdown 底稿和 CSV 指标表。

## 快速运行

需要 **Python 3.10 或更高版本，推荐 Python 3.12**。首次安装依赖需要访问软件包仓库。

### 使用 uv

在仓库根目录执行：

```sh
uv sync --locked --extra reports
uv run --locked --extra reports annual-report-assistant --open
```

默认地址为 `http://127.0.0.1:8787/`。点击“用贵州茅台公开年报试一试”，即可体验完整流程；也可以上传自己的文字版 PDF。

已有 uv 时，也可以双击 macOS 的 `start.command` 或 `年报分析助手.command`，Windows 使用 `start.ps1`，Linux 使用 `bash scripts/run.sh`。启动脚本只使用当前仓库及其虚拟环境，不依赖其他项目的本机路径。uv 首次运行会同步锁定的依赖。

### 使用 pip

macOS / Linux：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[reports]'
.venv/bin/python -m openharness.annual_reports --open
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[reports]"
.\.venv\Scripts\python.exe -m openharness.annual_reports --open
```

使用 pip 时依据 `pyproject.toml` 解析依赖；需要按锁文件复现环境时使用 uv。PowerShell 脚本遵循本机执行策略；也可以直接运行上面的 Python 命令。

## 使用流程

上传年报 → 提取候选指标 → 原文复核 → 跨年对比 → 问答与解读 → 导出底稿

1. 导入同一家公司的相邻年度完整年报，单份不超过 25 MB、500 页。
2. 点击每条候选值，查看源页，核对期间、金额、单位、币种和口径。
3. 确认本期及上期数据，查看程序计算的变化和数据观察。
4. 使用“本地查找”询问指标或检索原文。
5. 如需模型解释，选择“DeepSeek 解读”，检查请求预览后再确认发送。
6. 导出底稿。资料库删除的是本应用保存的副本与核对记录，原始上传文件不会被修改。

## 可选：配置 DeepSeek

本地功能不需要密钥。需要云端解读时，可选择以下一种方式：

```sh
uv run --locked --extra reports oh setup deepseek
```

或通过环境变量提供密钥：

```sh
export DEEPSEEK_API_KEY="你的密钥"
uv run --locked --extra reports annual-report-assistant --open
```

PowerShell 使用 `$env:DEEPSEEK_API_KEY = "你的密钥"`。不要把真实密钥写入源码或提交到 Git。

`oh setup deepseek` 使用 OpenHarness 的配置与凭据解析；配置入口会隐藏输入。已有可用的系统 keyring 时可使用它，否则可能采用仅限当前用户访问的本地凭据文件。配置已保存不等于接口已连通或账户余额充足。

`.env.example` 是配置模板。**本地 Python 程序不会自动读取 `.env`**；本地运行请使用环境变量或 `oh setup`。Docker Compose 的 `env_file` 会读取复制后的 `.env`。

## 数据在哪里

| 内容 | 默认位置 / 规则 |
|---|---|
| 导入副本、提取数据与复核记录 | `~/.openharness/data/annual_reports/` |
| 指定年报工作区 | 环境变量 `ANNUAL_REPORT_DATA_DIR`，或启动参数 `--data-dir` |
| OpenHarness 配置 | `~/.openharness/`，可用 `OPENHARNESS_CONFIG_DIR` 指定 |
| 通用数据根目录 | 可用 `OPENHARNESS_DATA_DIR` 指定，年报工作区位于其 `annual_reports/` 子目录 |
| 导出底稿 | 浏览器下载目录 |

本地提取、渲染、核对、计算和检索不调用模型。只有明确确认后，预览中的问题、选取节选和已核对事实才会发送给 DeepSeek；API Key 不进入预览正文。

预览绑定资料版本，十分钟过期且只能使用一次。请求仅连接官方 HTTPS 接口，不跟随重定向。来源编号会进行检查，但编号存在不能证明全部语义正确，模型解读仍需复核。

本应用没有完成全面安全审计或企业级 DLP。云端服务接收获准发送的内容，其数据处理规则仍然适用。本地删除不会同时删除已下载文件或服务方的留存。

## 技术实现

项目将年报检索、原文页读取和财务对比封装为 OpenHarness 原生只读工具，接入工具注册、参数校验、权限检查、执行上下文和统一结果返回机制。

财务业务模块负责证据管理、口径检查与数值计算；OpenHarness 提供工具执行基础；DeepSeek 基于用户批准的材料生成解释。本地提取、复核、计算与检索无需模型密钥。

**技术栈：** Python、OpenHarness、Pydantic、pypdf、pdfplumber、pypdfium2、Decimal、DeepSeek API、HTML/CSS/JavaScript。

### 原生工具接入

年报应用通过 `annual-report-assistant` 或 `oh reports` 启动，注册三个原生只读工具：

| 工具 | 用途 |
|---|---|
| `annual_report_search` | 本地指标问答与原文检索 |
| `annual_report_page` | 读取已导入报告的指定物理页 |
| `annual_report_compare` | 获取带确认状态的比较结果 |

实际请求经过 `BaseTool`、`ToolRegistry`、Pydantic 参数校验、`PermissionChecker` 的 PLAN 检查、`ToolExecutionContext`，再返回带来源的 `ToolResult`。该入口不加载通用 Shell 或任意文件工具。

模型解读采用一次固定的已批准请求，不开放自主工具调用循环，也不自动覆盖已确认数字。完整接入设计见 [架构说明](docs/annual_reports/ARCHITECTURE.md)。

### 可选：运行通用 OpenHarness

Python 核心和 `ohmo` 源码均已保留。通用终端界面还需要 Node.js / npm：

```sh
cd frontend/terminal
npm ci
cd ../..
uv run --locked --extra reports oh
```

`uv run --locked --extra reports ohmo --help` 可查看可选个人助手入口。通用 Agent 的文件、网络和权限边界与年报专用入口不同，应分别检查配置。

上游历史介绍保留在 [OpenHarness README](README.openharness.md) 与 [中文说明](README.openharness.zh-CN.md)。其中安装与发布步骤针对原项目，当前仓库的安装请以本 README 为准。

## Docker：本机运行示例

```sh
cp .env.example .env
docker compose up --build
```

打开 `http://127.0.0.1:8787/`。Compose 只向本机映射端口，并为工作数据提供持久化目录。本地功能可不填写密钥；需要解读时再填写 `.env` 中的 `DEEPSEEK_API_KEY` 并重启服务。

这是本机部署配置，未提供公开互联网服务所需的身份认证。公开部署前，应独立设计访问控制和数据隔离。

## 测试与复现

```sh
uv sync --locked --extra reports --extra dev
uv run --locked --extra reports --extra dev pytest tests/test_annual_reports -q
uv run --locked --extra reports --extra dev ruff check src/openharness/annual_reports tests/test_annual_reports
uv run --locked --extra reports python scripts/evaluate_annual_reports.py
uv build --wheel
```

完整离线测试可运行 `uv run --locked --extra reports --extra dev python scripts/test_offline.py`；该脚本会隔离配置、运行数据和模型密钥。当前打包验证结果见 [发布验证记录](docs/RELEASE_VALIDATION.md)。

离线年报样本验收核对同一家公司的两份公开报告，金额及同比结果见 [验收记录](docs/annual_reports/EVALUATION.md)。这些结果不代表所有年报的通用准确率，也没有证明用户效率提升。

`scripts/check_reports_http.py` 仅对内置公开示例运行真实本机 HTTP 验收。显式添加 `--live-model` 才会进行收费的真实模型调用；使用前检查所选服务及账户。

## 项目结构

```text
src/openharness/                 OpenHarness 核心与年报应用
  annual_reports/               提取、复核、计算、原生工具桥、服务与界面
ohmo/                           可选个人助手
frontend/terminal/              可选通用终端前端源码
data/annual_reports_demo/       公开示例、来源与独立核对数据
tests/                          框架与业务测试
scripts/                        启动和验收脚本
docs/annual_reports/            产品、架构、面试与评测材料
outputs/annual_reports/         公开示例底稿与界面截图
```

## 验证与范围

当前公开示例采用贵州茅台 2024 年与 2023 年年度报告。第一版支持文字版人民币年度报告；样本验证结果不代表所有年报的通用准确率，模型解读仍需结合原文复核。

扫描件需要先 OCR；不自动换汇。半年、季度、月度、分部和母公司口径的问题不以全年合并数代答，优先返回原文检索与限制说明。此工具用于辅助阅读和核对，不生成买卖结论。

## 来源与发布

OpenHarness 基础代码保留原 MIT 许可证与版权声明。年报模块及本仓库的来源说明见 [NOTICE](NOTICE)，公开年报与其他材料见 [第三方说明](THIRD_PARTY_NOTICES.md)。

GitHub 发布准备、忽略文件和独立安装检查见 [发布说明](docs/RELEASING.md)。仓库不包含本机虚拟环境、真实密钥、上传资料、运行会话或默认启用的定时写仓库工作流。
