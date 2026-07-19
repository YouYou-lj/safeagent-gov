# SafeAgent-Gov 跨平台项目目录结构规划.md

# SafeAgent-Gov 跨平台项目目录结构规划

> 适用项目：智御政安 SafeAgent-Gov
> 适用阶段：MVP 开发、三端客户端构建、GitHub 仓库整理、后续 Release 发布
> 核心原则：公共能力只维护一份，平台差异单独管理，安装包不进入源码仓库。

---

## 1. 总体目录设计原则

SafeAgent-Gov 不建议拆成 macOS、Windows、Linux 三个完全独立项目，也不建议每个平台都复制一整套 Skills、MCP、多 Agent、Graphify 和 Eval。

推荐采用：

```text
一个总仓库
+
公共核心能力目录
+
三端平台专属目录
+
统一构建与发布目录
```

核心逻辑是：

```text
core/        放治理技术体系
backend/     放 Python 后端
frontend/    放 Vue 前端
desktop/     放 mac / windows / linux 三端客户端配置
docs/        放文档
scripts/     放构建脚本
release/     放本地构建产物，不提交 Git
```

其中，真正的项目核心是：

```text
Skills
MCP
多路由 Agent
Graphify
AgentSecEval
TraceAudit
Model Gateway
```

这些能力不应该在 macOS、Windows、Linux 三个目录里重复写三份，而是统一放在公共核心目录中，由三个客户端共同调用。

---

## 2. 推荐完整目录结构

```text
safeagent-gov/
├── README.md
├── pyproject.toml
├── package.json
├── pnpm-lock.yaml
├── .gitignore
├── .env.example
│
├── core/                         # 公共核心能力，不区分系统
│   ├── skills/                   # 治理 Skills
│   │   ├── promptshield-gov/
│   │   ├── toolguard-gov/
│   │   ├── skillscan-gov/
│   │   ├── sensitive-data-gov/
│   │   ├── compliance-gov/
│   │   ├── traceaudit-gov/
│   │   ├── agentseceval-gov/
│   │   └── graphify-gov/
│   │
│   ├── mcp/                      # MCP 工具治理
│   │   ├── safe-file-mcp/
│   │   ├── safe-email-mcp/
│   │   ├── safe-shell-mcp/
│   │   ├── safe-db-mcp/
│   │   └── safe-browser-mcp/
│   │
│   ├── agents/                   # 多 Agent 路由
│   │   ├── safe-router-gov/
│   │   ├── promptshield-agent/
│   │   ├── tool-risk-agent/
│   │   ├── compliance-agent/
│   │   ├── audit-agent/
│   │   └── eval-agent/
│   │
│   ├── graphify/                 # 能力图谱调度
│   │   ├── graph_builder.py
│   │   ├── repository_scanner.py
│   │   ├── metadata_extractor.py
│   │   ├── graph_retriever.py
│   │   ├── route_planner.py
│   │   └── graph_health.py
│   │
│   ├── eval/                     # 政务服务安全测试
│   │   ├── gov_service_cases/
│   │   ├── owasp_cases/
│   │   ├── mcp_security_cases/
│   │   ├── run_all_eval.py
│   │   └── eval_report_template.md
│   │
│   ├── audit/                    # 审计溯源
│   │   ├── audit_logger.py
│   │   ├── trace_schema.json
│   │   └── report_generator.py
│   │
│   ├── model_gateway/            # 多模型网关
│   │   ├── gateway.py
│   │   ├── routing_policy.yaml
│   │   └── providers/
│   │
│   └── configs/                  # 公共策略配置
│       ├── skill_registry.yaml
│       ├── mcp_registry.yaml
│       ├── tool_policy.yaml
│       ├── graphify_policy.yaml
│       └── model_policy.yaml
│
├── backend/                      # Python / FastAPI 后端
│   ├── main.py
│   ├── desktop_boot.py
│   ├── api/
│   │   ├── agent_api.py
│   │   ├── skills_api.py
│   │   ├── mcp_api.py
│   │   ├── graphify_api.py
│   │   ├── audit_api.py
│   │   └── eval_api.py
│   ├── services/
│   ├── database/
│   └── schemas/
│
├── frontend/                     # Vue 前端公共源码
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── views/
│       │   ├── Dashboard.vue
│       │   ├── AgentPlayground.vue
│       │   ├── SkillCenter.vue
│       │   ├── MCPGateway.vue
│       │   ├── GraphifyCenter.vue
│       │   ├── RouterMonitor.vue
│       │   ├── ApprovalCenter.vue
│       │   ├── AuditTrace.vue
│       │   ├── EvalCenter.vue
│       │   └── ModelSettings.vue
│       ├── components/
│       ├── api/
│       ├── router/
│       └── stores/
│
├── desktop/                      # 桌面客户端总目录
│   ├── src-tauri/                # Tauri 公共配置
│   │   ├── Cargo.toml
│   │   ├── tauri.conf.json
│   │   └── src/
│   │       └── main.rs
│   │
│   ├── mac/                      # macOS 专属文件
│   │   ├── README.md
│   │   ├── tauri.macos.conf.json
│   │   ├── build-mac.sh
│   │   ├── package-dmg.sh
│   │   ├── entitlements.plist
│   │   ├── notarize.sh
│   │   ├── icons/
│   │   │   ├── icon.icns
│   │   │   └── dmg-background.png
│   │   └── resources/
│   │       └── mac-install-guide.md
│   │
│   ├── windows/                  # Windows 专属文件
│   │   ├── README.md
│   │   ├── tauri.windows.conf.json
│   │   ├── build-windows.ps1
│   │   ├── package-msi.ps1
│   │   ├── installer.nsi
│   │   ├── icons/
│   │   │   └── icon.ico
│   │   └── resources/
│   │       └── windows-install-guide.md
│   │
│   ├── linux/                    # Linux 专属文件
│   │   ├── README.md
│   │   ├── tauri.linux.conf.json
│   │   ├── build-linux.sh
│   │   ├── package-appimage.sh
│   │   ├── package-deb.sh
│   │   ├── icons/
│   │   │   └── icon.png
│   │   └── resources/
│   │       └── linux-install-guide.md
│   │
│   └── binaries/                 # PyInstaller 生成的后端 sidecar，不建议提交
│       ├── mac/
│       ├── windows/
│       └── linux/
│
├── scripts/                      # 通用构建脚本
│   ├── build-all.sh
│   ├── build-backend.sh
│   ├── build-frontend.sh
│   ├── clean.sh
│   └── release.sh
│
├── docs/                         # 文档
│   ├── system_plan.md
│   ├── mac_client_dev.md
│   ├── windows_client_dev.md
│   ├── linux_client_dev.md
│   ├── project_structure_plan.md
│   ├── install_prompt.md
│   └── testing_prompt.md
│
├── release/                      # 本地构建产物，不提交 Git
│   ├── mac/
│   ├── windows/
│   └── linux/
│
└── .github/
    └── workflows/
        ├── build-macos.yml
        ├── build-windows.yml
        ├── build-linux.yml
        └── release.yml
```

---

## 3. 各目录职责说明

### 3.1 `core/`：公共治理技术体系

`core/` 是 SafeAgent-Gov 的核心，三端客户端都调用这里的能力。

```text
core/
├── skills/
├── mcp/
├── agents/
├── graphify/
├── eval/
├── audit/
├── model_gateway/
└── configs/
```

这里放的是项目真正的创新点：

| 子目录 | 作用 |
|---|---|
| `skills/` | PromptShield、ToolGuard、SkillScan 等治理技能 |
| `mcp/` | 文件、邮件、Shell、数据库等 MCP 工具治理 |
| `agents/` | SafeRouter、多子智能体、风险聚合器 |
| `graphify/` | 能力图谱构建、检索、路径推荐 |
| `eval/` | 政务服务安全测试案例和自动评测 |
| `audit/` | trace_id、审计日志、报告生成 |
| `model_gateway/` | 云端模型、本地模型、私有模型统一路由 |
| `configs/` | 技能注册表、MCP 策略、模型策略 |

这些内容不要重复放到 mac、windows、linux 目录下。

---

### 3.2 `backend/`：Python 后端

`backend/` 负责把 `core/` 中的治理能力封装成 API，供前端和桌面客户端调用。

```text
backend/
├── main.py
├── desktop_boot.py
├── api/
├── services/
├── database/
└── schemas/
```

其中：

| 文件/目录 | 作用 |
|---|---|
| `main.py` | Web / 服务端模式入口 |
| `desktop_boot.py` | 桌面客户端 Sidecar 入口 |
| `api/` | Skills、MCP、Graphify、Eval、Audit API |
| `services/` | 业务编排层 |
| `database/` | SQLite / PostgreSQL 访问 |
| `schemas/` | Pydantic 数据结构 |

---

### 3.3 `frontend/`：Vue 前端

`frontend/` 只放一份公共前端，不区分 macOS、Windows、Linux。

```text
frontend/src/views/
├── Dashboard.vue
├── AgentPlayground.vue
├── SkillCenter.vue
├── MCPGateway.vue
├── GraphifyCenter.vue
├── RouterMonitor.vue
├── ApprovalCenter.vue
├── AuditTrace.vue
├── EvalCenter.vue
└── ModelSettings.vue
```

平台差异由 Tauri 配置和运行环境处理，前端页面尽量保持一致。

---

### 3.4 `desktop/`：三端客户端配置

`desktop/` 用于放置跨平台客户端相关内容。

```text
desktop/
├── src-tauri/
├── mac/
├── windows/
├── linux/
└── binaries/
```

其中：

| 目录 | 作用 |
|---|---|
| `src-tauri/` | Tauri 公共配置 |
| `mac/` | macOS 构建、签名、公证、dmg 配置 |
| `windows/` | Windows 构建、msi/nsis 配置 |
| `linux/` | Linux 构建、AppImage/deb 配置 |
| `binaries/` | PyInstaller 生成的后端 Sidecar，本地构建用，不建议提交 |

---

## 4. 三个平台目录具体放置内容

### 4.1 macOS 目录

```text
desktop/mac/
├── README.md
├── tauri.macos.conf.json
├── build-mac.sh
├── package-dmg.sh
├── entitlements.plist
├── notarize.sh
├── icons/
│   ├── icon.icns
│   └── dmg-background.png
└── resources/
    └── mac-install-guide.md
```

说明：

| 文件 | 作用 |
|---|---|
| `README.md` | macOS 开发说明 |
| `tauri.macos.conf.json` | macOS 专属 Tauri 配置 |
| `build-mac.sh` | macOS 构建脚本 |
| `package-dmg.sh` | dmg 打包脚本 |
| `entitlements.plist` | macOS 权限配置 |
| `notarize.sh` | Apple 公证脚本，正式分发阶段使用 |
| `icons/icon.icns` | macOS 图标 |
| `resources/mac-install-guide.md` | macOS 安装说明 |

---

### 4.2 Windows 目录

```text
desktop/windows/
├── README.md
├── tauri.windows.conf.json
├── build-windows.ps1
├── package-msi.ps1
├── installer.nsi
├── icons/
│   └── icon.ico
└── resources/
    └── windows-install-guide.md
```

说明：

| 文件 | 作用 |
|---|---|
| `README.md` | Windows 开发说明 |
| `tauri.windows.conf.json` | Windows 专属 Tauri 配置 |
| `build-windows.ps1` | Windows PowerShell 构建脚本 |
| `package-msi.ps1` | MSI 打包脚本 |
| `installer.nsi` | NSIS 安装器配置 |
| `icons/icon.ico` | Windows 图标 |
| `resources/windows-install-guide.md` | Windows 安装说明 |

---

### 4.3 Linux 目录

```text
desktop/linux/
├── README.md
├── tauri.linux.conf.json
├── build-linux.sh
├── package-appimage.sh
├── package-deb.sh
├── icons/
│   └── icon.png
└── resources/
    └── linux-install-guide.md
```

说明：

| 文件 | 作用 |
|---|---|
| `README.md` | Linux 开发说明 |
| `tauri.linux.conf.json` | Linux 专属 Tauri 配置 |
| `build-linux.sh` | Linux 构建脚本 |
| `package-appimage.sh` | AppImage 打包脚本 |
| `package-deb.sh` | deb 打包脚本 |
| `icons/icon.png` | Linux 图标 |
| `resources/linux-install-guide.md` | Linux 安装说明 |

---

## 5. 构建产物放置规则

本地构建出来的安装包放到 `release/`，但不要提交 Git。

```text
release/
├── mac/
│   ├── SafeAgent-Gov.dmg
│   └── safeagent-gov-macos-arm64-v0.1.0.zip
│
├── windows/
│   ├── SafeAgent-Gov-Setup.exe
│   ├── SafeAgent-Gov.msi
│   └── safeagent-gov-windows-x64-v0.1.0.zip
│
└── linux/
    ├── SafeAgent-Gov.AppImage
    ├── safeagent-gov.deb
    └── safeagent-gov-linux-x64-v0.1.0.tar.gz
```

安装包发布位置：

```text
GitHub Releases
```

不建议把 `.dmg`、`.exe`、`.msi`、`.AppImage`、`.deb` 直接提交到源码仓库。

---

## 6. Git 应提交哪些内容

应该提交：

```text
core/
backend/
frontend/
desktop/mac/
desktop/windows/
desktop/linux/
scripts/
docs/
.github/workflows/
pyproject.toml
package.json
pnpm-lock.yaml
README.md
.gitignore
.env.example
```

这些是源码、配置、脚本和文档，是别人复现项目所必需的内容。

---

## 7. Git 不应提交哪些内容

不建议提交：

```text
release/
dist/
build/
target/
desktop/binaries/
node_modules/
.venv/
__pycache__/
reports/
logs/
data/
audit/
.env
*.dmg
*.exe
*.msi
*.AppImage
*.deb
*.zip
*.tar.gz
*.key
*.pem
*.p12
```

原因：

| 内容 | 不提交原因 |
|---|---|
| 安装包 | 体积大，版本库膨胀 |
| 构建缓存 | 可重新生成 |
| 虚拟环境 | 不跨平台 |
| 依赖目录 | 可通过 pnpm / uv 安装 |
| 报告与日志 | 运行后生成 |
| 密钥证书 | 涉及安全风险 |

---

## 8. `.gitignore` 建议

```gitignore
# Node
node_modules/
dist/
.pnpm-store/

# Python
.venv/
venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Rust / Tauri
target/
desktop/src-tauri/target/
desktop/binaries/

# Build outputs
release/
build/
*.dmg
*.pkg
*.msi
*.exe
*.AppImage
*.deb
*.rpm
*.zip
*.tar.gz

# Logs and generated reports
*.log
logs/
reports/

# Local runtime data
.safeagent-gov/
data/
audit/
graphify_db/

# Secrets
.env
.env.local
*.pem
*.key
*.p12
*.mobileprovision

# OS
.DS_Store
Thumbs.db
```

---

## 9. 推荐开发顺序

### 第一阶段：MVP 目录搭建

```text
core/
backend/
frontend/
desktop/mac/
docs/
```

先跑通 macOS 本地开发，因为 macOS 是主力开发环境。

### 第二阶段：Windows 构建适配

```text
desktop/windows/
.github/workflows/build-windows.yml
```

重点处理：

```text
路径分隔符
PyInstaller Windows exe
MSI / NSIS 打包
Windows Defender 误报说明
```

### 第三阶段：Linux 构建适配

```text
desktop/linux/
.github/workflows/build-linux.yml
```

重点处理：

```text
WebKitGTK 依赖
AppImage
deb
Docker Compose 服务模式
```

### 第四阶段：统一 Release

```text
.github/workflows/release.yml
```

通过 tag 自动发布：

```bash
git tag v0.1.0
git push origin v0.1.0
```

生成：

```text
macOS dmg
Windows msi / exe
Linux AppImage / deb
```

---

## 10. 三端构建流程建议

### macOS

```bash
cd safeagent-gov
pnpm install
uv sync
bash desktop/mac/build-mac.sh
```

### Windows

```powershell
cd safeagent-gov
pnpm install
uv sync
powershell -ExecutionPolicy Bypass -File desktop/windows/build-windows.ps1
```

### Linux

```bash
cd safeagent-gov
pnpm install
uv sync
bash desktop/linux/build-linux.sh
```

---

## 11. GitHub Actions 建议

```text
.github/workflows/
├── build-macos.yml
├── build-windows.yml
├── build-linux.yml
└── release.yml
```

职责：

| Workflow | 作用 |
|---|---|
| `build-macos.yml` | 构建 macOS app / dmg |
| `build-windows.yml` | 构建 Windows exe / msi |
| `build-linux.yml` | 构建 Linux AppImage / deb |
| `release.yml` | 打 tag 后汇总产物并上传 GitHub Release |

---

## 12. 最终目录理解

可以简单记成：

```text
core/       技术体系
backend/    后端接口
frontend/   前端界面
desktop/    三端壳和构建
docs/       文档
scripts/    通用脚本
release/    安装包，不提交
```

---

## 13. 最终结论

SafeAgent-Gov 的 macOS、Windows、Linux 不应各自复制完整项目，而应采用：

```text
公共核心统一维护
平台差异分目录管理
构建产物统一 Release 发布
```

最终结构为：

```text
core/                放 Skills、MCP、多 Agent、Graphify、Eval
backend/             放 Python/FastAPI 后端
frontend/            放 Vue 前端
desktop/mac/         放 macOS 专属构建文件
desktop/windows/     放 Windows 专属构建文件
desktop/linux/       放 Linux 专属构建文件
release/             放本地安装包，不提交 Git
```

一句话：

> mac、windows、linux 只放平台专属构建文件；公共的 Skills、MCP、多路由 Agent、Graphify、Eval 全部放在 core 里统一维护。
