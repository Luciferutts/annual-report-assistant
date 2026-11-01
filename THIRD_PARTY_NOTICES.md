# 第三方来源与材料说明

## OpenHarness

- 上游仓库：[HKUDS/OpenHarness](https://github.com/HKUDS/OpenHarness)
- 源码基线：`1498a87806d5a3a7dc159b2eb81d9283dc21cd99`
- 原许可证：MIT，Copyright (c) 2025 OpenHarness Contributors。
- 原版权和许可全文保留在 [LICENSE](LICENSE)，项目层面的说明见 [NOTICE](NOTICE)。

年报业务在该框架上新增。工具基础接口、配置解析及其他保留的框架模块继续归属原作者；本仓库不把这些基础代码描述为全部独立原创。

## 公开年报示例

以下 PDF 为公开披露的参考资料，用于演示提取、核对与原文回查。它们属于各自发布主体或权利人的作品，**代码的 MIT 许可不自动适用于这些 PDF**。原文保持不变，文件哈希和披露链接记录在 [sources.json](data/annual_reports_demo/sources.json)。

| 文件 | 披露来源 | SHA-256 |
|---|---|---|
| `moutai-2024.pdf` | [贵州茅台官网：2024 年年度报告](https://www.moutaichina.com/mtgf/articleFileDir/2025-04/08/8055b7bed7db41bdbc617f4c9b9ec591.pdf) | `5299f4940e2ce4e91084b73dc457d558b9d335fa76fbfee6227e4254eb7f4a30` |
| `moutai-2023.pdf` | [巨潮资讯：2023 年年度报告](https://dataclouds.cninfo.com.cn/shgonggao/2024/2024-04-03/93d5007bf0fa11ee84b5fa163e26e5de.pdf) | `2125ff97a452ea79b0d784e2432f7d224b6aecc330b644b593477d69e22f4ed1` |

年度为报告所属期间，材料为历史披露，不代表最新经营情况。示例底稿中的财务数字与文字节选来自对应原文，输出中的原文出处应保留。

## Python 与前端依赖

Python 依赖范围和锁定版本位于 `pyproject.toml`、`uv.lock`。通用终端和可选仪表盘的 npm 依赖记录在各自的 `package.json`、`package-lock.json`。

这些依赖在安装时由软件包仓库提供，分别适用其原许可证；本仓库没有复制虚拟环境或 `node_modules`。发布衍生构建时，应保留实际分发依赖所要求的声明。
