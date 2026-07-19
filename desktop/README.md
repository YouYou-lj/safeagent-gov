# GovSafeAgent 跨平台桌面客户端

本目录维护一套 Tauri 2 + Vue 3 + FastAPI Sidecar 公共实现。macOS、Windows、Linux 目录只保存本平台的
构建、签名、安装包和依赖差异，不能复制 `src-tauri/`、`frontend-vue/` 或 Python 安全核心。

```text
desktop/
├── src-tauri/       # 三个平台共享的 Rust 壳、权限和基础 Tauri 配置
├── scripts/         # 三个平台共享的 Sidecar/Tauri 调度脚本
├── icon.svg         # 可编辑的公共品牌源文件
├── mac/             # 仅 macOS 配置、图标、签名、公证与 DMG
├── windows/         # 仅 Windows 配置、图标、MSI/NSIS 与签名边界
└── linux/           # 仅 Linux 配置、图标、AppImage/deb 与系统依赖
```

公共 `tauri.conf.json` 不声明平台安装包或平台图标；所有 Tauri 命令都会自动合并当前主机的配置。
结构门禁会拒绝公共图标目录以及平台目录中的 `src-tauri`、前端或 Python 核心副本。
公共 `package.json` 也不保存平台签名/打包实现；`npm run build` 只负责按当前主机分发到对应平台脚本。
Tauri 的 `src-tauri/gen/` 属于主机生成 schema，已忽略，避免三种设备提交互相覆盖的生成差异。

## 公共安全边界

- Tauri 只启动清单内 `safeagent-backend` Sidecar，不向 WebView 开放 Shell 权限。
- Sidecar 只绑定随机 `127.0.0.1`，短期身份经 Rust IPC 进入 Vue 内存，不写命令行或配置文件。
- 数据使用 Tauri 提供的每用户 App Data 目录；Python 默认路径同时支持 macOS Application Support、
  Windows LocalAppData 和 Linux XDG Data Home。
- Skills、MCP、Graphify、Agent 与评测始终复用仓库根目录的唯一实现。

## 通用开发

```bash
./scripts/setup_uv_env.sh
cd frontend-vue && npm ci --ignore-scripts --no-audit --no-fund
cd ../desktop && npm ci --ignore-scripts --no-audit --no-fund
npm run dev
```

本机冻结 Sidecar 可用 `npm run sidecar:build && npm run sidecar:verify` 验证。原生安装包不能跨系统伪造，
统一使用 `npm run build` 分发到当前平台脚本：

| 平台 | 原生构建入口 | 安装包 | 本地数据目录 |
|---|---|---|---|
| macOS 13+ | `bash mac/build-mac.sh` | `.app` / `.dmg` | `~/Library/Application Support/com.safeagent.gov` |
| Windows 10/11 x64 | `windows\\build-windows.ps1` | `.msi` / NSIS `.exe` | `%LOCALAPPDATA%\\SafeAgent-Gov` |
| Linux x64/arm64 | `bash linux/build-linux.sh` | `.AppImage` / `.deb` | `$XDG_DATA_HOME/safeagent-gov` |

产物统一复制到仓库根 `release/`，该目录中的安装包不会进入 Git。Tag 流水线只创建 draft Release；正式
发布前必须完成平台签名/公证复核，签名凭据只允许放在受保护的 CI Secret 或系统密钥链中。

## 固定版本

- Python 3.11.12、uv 0.7.0、PyInstaller 6.21.0
- Node.js >=22.12、Tauri CLI 2.11.4
- Rust 1.97.1、Tauri 2.11.5、Shell Plugin 2.3.5

各平台依赖、边界和验证方式见 [macOS](mac/README.md)、[Windows](windows/README.md) 与
[Linux](linux/README.md)。
