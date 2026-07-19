# mac_client_dev.md

# SafeAgent-Gov macOS 客户端开发方案

> 目标：构建适用于 macOS 的 SafeAgent-Gov 桌面客户端，优先支持 Apple Silicon M 系列芯片，同时兼容 Intel Mac。
> 核心定位：macOS 客户端是治理技能体系的本地运行与演示容器。

---

## 1. macOS 客户端定位

macOS 客户端主要面向：

```text
开发者本地测试
比赛现场演示
政企离线安全评测
本地模型 / 云端模型混合验证
```

M3 24GB + 512GB 设备适合承担 macOS 端开发与演示。

---

## 2. 技术栈

| 模块 | 技术 |
|---|---|
| 桌面壳 | Tauri |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus |
| 后端 | Python FastAPI Sidecar |
| Python 打包 | PyInstaller |
| 本地数据库 | SQLite |
| 图谱 | SQLite + NetworkX |
| 可选向量 | FAISS / Chroma |
| 本地模型 | Ollama 可选 |
| 打包产物 | `.app`、`.dmg`、`.zip` |

---

## 3. macOS 客户端目录结构

```text
apps/desktop/
├── package.json
├── vite.config.ts
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── views/
│   │   ├── Dashboard.vue
│   │   ├── SkillsCenter.vue
│   │   ├── MCPGateway.vue
│   │   ├── GraphifyCenter.vue
│   │   ├── EvalCenter.vue
│   │   └── AuditTrace.vue
│   └── api/
└── src-tauri/
    ├── Cargo.toml
    ├── tauri.conf.json
    ├── src/main.rs
    └── binaries/
        ├── safeagent-backend-aarch64-apple-darwin
        └── safeagent-backend-x86_64-apple-darwin
```

---

## 4. macOS 后端 Sidecar

### 4.1 入口文件

```python
# safeagent_gov/desktop_boot.py

import uvicorn
from pathlib import Path
from safeagent_gov.api import create_app

def main():
    app_data = Path.home() / ".safeagent-gov"
    app_data.mkdir(parents=True, exist_ok=True)

    app = create_app(
        data_dir=app_data,
        desktop_mode=True,
        safe_mode=True
    )

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")

if __name__ == "__main__":
    main()
```

### 4.2 macOS 打包命令

```bash
pyinstaller safeagent_gov/desktop_boot.py \
  --name safeagent-backend-aarch64-apple-darwin \
  --onefile \
  --add-data "governance-skills-pack:governance-skills-pack" \
  --add-data "mcp-governance-pack:mcp-governance-pack" \
  --add-data "graphify-pack:graphify-pack" \
  --add-data "eval-pack:eval-pack"
```

---

## 5. Tauri 配置重点

`apps/desktop/src-tauri/tauri.conf.json`：

```json
{
  "productName": "SafeAgent-Gov",
  "version": "0.1.0",
  "identifier": "com.safeagent.gov",
  "build": {
    "beforeDevCommand": "pnpm dev",
    "beforeBuildCommand": "pnpm build",
    "frontendDist": "../dist",
    "devUrl": "http://localhost:5173"
  },
  "bundle": {
    "active": true,
    "targets": ["app", "dmg"],
    "resources": [
      "../../governance-skills-pack",
      "../../mcp-governance-pack",
      "../../graphify-pack",
      "../../eval-pack"
    ],
    "externalBin": ["binaries/safeagent-backend"]
  }
}
```

---

## 6. macOS 本地数据目录

```text
~/.safeagent-gov/
├── config/
├── data/
├── audit/
├── graphify/
├── reports/
├── eval/
└── logs/
```

---

## 7. macOS 启动流程

```text
用户打开 SafeAgent-Gov.app
↓
Tauri 启动
↓
自动启动 Python Sidecar
↓
检查 127.0.0.1:8765 健康状态
↓
加载 Vue 控制台
↓
初始化 Skills、MCP、Graphify、Eval
↓
显示 Dashboard
```

---

## 8. macOS 模型支持

云端模型：

```text
OpenAI
Claude
Gemini
DeepSeek
Qwen
Kimi
智谱
```

本地模型推荐 Ollama：

```bash
brew install ollama
ollama pull qwen3-embedding:0.6b
```

客户端只检测 Ollama 是否存在，不强制内置模型。

---

## 9. macOS 安全设置

1. 默认启用 Safe Mode；
2. Shell MCP 默认阻断；
3. File MCP 只能访问用户选择目录；
4. 邮件 MCP 只模拟发送；
5. 数据库 MCP 默认只读；
6. 审计文件默认存本地；
7. 不自动上传用户文件到云端。

---

## 10. macOS 构建命令

```bash
pnpm install
uv sync
pnpm tauri dev
pnpm tauri build
```

产物目录：

```text
apps/desktop/src-tauri/target/release/bundle/
├── macos/
└── dmg/
```

---

## 11. macOS 发布包

```text
release/mac/
├── SafeAgent-Gov.app
├── SafeAgent-Gov_0.1.0_aarch64.dmg
└── safeagent-gov-macos-arm64-v0.1.0.zip
```

---

## 12. macOS 测试清单

| 测试项 | 目标 |
|---|---|
| 启动测试 | App 能打开 |
| Sidecar 测试 | 后端自动启动 |
| Skills 测试 | PromptShield、ToolGuard 能运行 |
| MCP 测试 | File、Email、Shell MCP 能被管控 |
| Graphify 测试 | 能构建能力图谱 |
| Eval 测试 | 能运行政务服务安全测试 |
| Audit 测试 | 能生成 trace_id 和报告 |
| 模型测试 | 云端/本地模型配置可保存 |

---

## 13. macOS 开发结论

macOS 客户端适合作为首个开发版本。建议优先完成：

```text
macOS arm64 MVP
↓
Windows x64
↓
Linux x64
```
