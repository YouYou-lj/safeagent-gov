# windows_client_dev.md

# SafeAgent-Gov Windows 客户端开发方案

> 目标：构建适用于 Windows 10/11 x64 的 SafeAgent-Gov 客户端。
> 核心定位：Windows 客户端用于政企办公环境、学校实验室电脑、评审电脑和普通用户桌面环境中的治理技能体系验证。

---

## 1. Windows 客户端定位

Windows 端是最重要的实际用户端之一，因为政企办公电脑大量使用 Windows。
该客户端应突出：

```text
安装简单
不依赖命令行经验
默认安全模式
可运行政务服务安全测试
可查看审计报告
```

---

## 2. 技术栈

| 模块 | 技术 |
|---|---|
| 桌面壳 | Tauri |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus |
| 后端 | Python FastAPI Sidecar |
| 后端打包 | PyInstaller `.exe` |
| 本地数据库 | SQLite |
| 图谱 | SQLite + NetworkX |
| 可选向量 | FAISS / Chroma |
| 安装包 | `.msi`、`.exe`、`.zip` |
| 本地模型 | Ollama for Windows 可选 |

---

## 3. Windows 客户端目录结构

```text
apps/desktop/
└── src-tauri/
    └── binaries/
        └── safeagent-backend-x86_64-pc-windows-msvc.exe
```

运行目录：

```text
%USERPROFILE%\.safeagent-gov\
├── config\
├── data\
├── audit\
├── graphify\
├── reports\
├── eval\
└── logs\
```

---

## 4. Windows 后端 Sidecar

### Windows 打包命令

```powershell
pyinstaller safeagent_gov\desktop_boot.py `
  --name safeagent-backend-x86_64-pc-windows-msvc `
  --onefile `
  --add-data "governance-skills-pack;governance-skills-pack" `
  --add-data "mcp-governance-pack;mcp-governance-pack" `
  --add-data "graphify-pack;graphify-pack" `
  --add-data "eval-pack;eval-pack"
```

注意 Windows 的 `--add-data` 分隔符是分号 `;`。

---

## 5. Windows Tauri 配置

```json
{
  "productName": "SafeAgent-Gov",
  "version": "0.1.0",
  "identifier": "com.safeagent.gov",
  "bundle": {
    "active": true,
    "targets": ["msi", "nsis"],
    "externalBin": ["binaries/safeagent-backend"],
    "resources": [
      "../../governance-skills-pack",
      "../../mcp-governance-pack",
      "../../graphify-pack",
      "../../eval-pack"
    ]
  }
}
```

---

## 6. Windows 安全模式

1. 不真实执行 Shell 高危命令；
2. 不真实发送外部邮件；
3. 不删除真实文件；
4. File MCP 默认只允许访问用户选择目录；
5. 数据库写入默认审批；
6. 外部发送默认审批；
7. 所有测试都以模拟模式运行；
8. 所有结果写入本地审计报告。

---

## 7. Windows UI 重点

| 页面 | 重点 |
|---|---|
| 快速开始 | 一键运行安全测试 |
| Skills 中心 | 查看治理技能启用状态 |
| MCP 网关 | 查看工具是否被拦截 |
| 审计报告 | 一键导出 Markdown |
| 模型设置 | 配置云端 API Key 或本地 Ollama |
| 系统诊断 | 检查 Python Sidecar、SQLite、权限 |

---

## 8. Windows 本地模型支持

本地模型作为可选项：

```text
Ollama for Windows
LM Studio
vLLM 远程服务
```

客户端不内置大模型文件，只提供检测与配置。

---

## 9. Windows 构建环境

推荐在 GitHub Actions Windows Runner 上构建：

```text
Node.js 20
pnpm
Python 3.11
Rust stable
PyInstaller
Tauri CLI
```

---

## 10. Windows 构建命令

```powershell
pnpm install
uv sync
pyinstaller safeagent_gov\desktop_boot.py --name safeagent-backend-x86_64-pc-windows-msvc --onefile
pnpm tauri build
```

产物目录：

```text
apps\desktop\src-tauri\target\release\bundle\
├── msi\
└── nsis\
```

---

## 11. Windows 发布包

```text
release/windows/
├── SafeAgent-Gov_0.1.0_x64.msi
├── SafeAgent-Gov_0.1.0_x64-setup.exe
└── safeagent-gov-windows-x64-v0.1.0.zip
```

---

## 12. Windows 测试清单

| 测试项 | 目标 |
|---|---|
| 安装测试 | `.msi` 能安装 |
| 启动测试 | 应用能正常打开 |
| 后端测试 | Sidecar 自动启动 |
| 权限测试 | 无管理员权限也能运行基础功能 |
| MCP 测试 | 高危工具被阻断 |
| 报告测试 | 能导出 Markdown 报告 |
| 卸载测试 | 卸载不破坏用户数据 |
| 兼容测试 | Windows 10/11 x64 |

---

## 13. Windows 常见问题

### 安全软件误报

未签名 `.exe` 可能被 Windows Defender 或第三方安全软件警告。比赛阶段可以说明为未签名开发版，正式发布需代码签名证书。

### 路径分隔符

Windows 使用 `\`，跨平台代码中必须使用 `pathlib.Path`。

### 端口占用

默认后端端口：

```text
127.0.0.1:8765
```

如果被占用，应自动寻找备用端口，并通知前端。

---

## 14. Windows 开发结论

Windows 客户端是最适合面向政企办公环境的版本。开发重点是：

```text
安装简单
默认安全
测试可运行
报告可导出
不误执行高危操作
```
