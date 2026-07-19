# SafeAgent-Gov 跨平台架构

## 单一真相源

macOS、Windows、Linux 使用同一个 Vue 控制台、Tauri Rust 壳、FastAPI 后端和安全核心。平台目录不得出现
Skill、MCP、Agent、Graphify、模型网关或评测的副本。`research_technology/core/manifest.yaml` 负责把规划分类
映射到仓库现有权威路径，`research_technology/` 是技术评审与论文写作入口。

```text
frontend-vue ──> desktop/src-tauri ──> host-native Python Sidecar
                                         │
             research_technology / safeagent_gov / agent_demo
                                         │
             macOS App Data / Windows LocalAppData / Linux XDG Data
```

## 平台边界

| 公共区 | macOS 差异 | Windows 差异 | Linux 差异 |
|---|---|---|---|
| `desktop/src-tauri/` | app/dmg、签名、公证 | MSI/NSIS、WebView2、Authenticode | AppImage/deb、WebKitGTK |
| `frontend-vue/` | 无业务分叉 | 无业务分叉 | 无业务分叉 |
| Python Sidecar | Application Support | LocalAppData、`.exe` | XDG Data、系统库 |

平台生成资产也遵守同一边界：公共品牌源为 `desktop/icon.svg`，`.icns` 只位于 `desktop/mac/icons/`，
`.ico` 与 Store/Square 资产只位于 `desktop/windows/icons/`，Linux PNG 只位于 `desktop/linux/icons/`。
公共 `desktop/src-tauri/tauri.conf.json` 只描述共享壳层；安装包 targets 和 icons 均由平台配置提供。
公共 `desktop/package.json` 只保留通用 dev/build/Sidecar 命令，原生签名和打包实现不得回流到其中；
`src-tauri/gen/` 是按主机生成的 Tauri schema，不进入 Git。仓库使用 `.gitattributes` 固定 Shell/源码为 LF、
PowerShell/NSIS 为 CRLF，并显式标记安装包与图标为二进制，减少跨设备无意义差异。
三平台 GitHub Actions 的 path filter 同时监听前端、后端、安全核心、Agent、配置、兼容入口、研究运行资源和
依赖锁文件；任何共享 Sidecar 输入变化都会触发三端各自在原生 runner 上重建。

Sidecar 的文件名由 `safeagent_gov.desktop_platform` 根据原生平台和 CPU 生成 Tauri 目标三元组。PyInstaller
只能在目标操作系统原生构建，安装包同样只在原生 GitHub runner 产生；本项目不把静态配置通过冒充为
Windows/Linux 二进制已验证。

## 构建与发布

`scripts/build_desktop.py` 只调度当前主机的平台脚本。各脚本先构建和验证冻结 Sidecar，再打 Tauri 安装包，
最后复制到 `release/<platform>/`。Git tag 流水线在三种 runner 上分别完成构建并汇总为 draft Release；只有
完成 Developer ID / Authenticode 等正式签名、公证和安全复核后才可人工发布，签名凭据不入库。

## 兼容目录说明

权威 Vue 前端位于 `frontend-vue/`，原 Streamlit 原型已经移除。根目录 `skills`、`mcp`、`benchmarks`、
`eval` 只保留跨平台 Python 兼容入口；真实技术源码位于 `research_technology/`，不维护双份实现。
