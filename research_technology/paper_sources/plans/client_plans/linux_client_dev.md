# linux_client_dev.md

# SafeAgent-Gov Linux 客户端开发方案

> 目标：构建适用于 Linux x64 的 SafeAgent-Gov 客户端，优先支持 Ubuntu / Debian 系发行版。
> 核心定位：Linux 客户端适合服务器、实验室、私有化部署、开发者环境和安全测试环境。

---

## 1. Linux 客户端定位

Linux 端的主要价值是：

```text
私有化部署
实验室环境测试
服务器端运行
开发者调试
安全评测自动化
```

相比 macOS 和 Windows，Linux 客户端可以更自然地与 Docker、MCP Server、Ollama、vLLM、Qdrant、PostgreSQL 等服务集成。

---

## 2. 技术栈

| 模块 | 技术 |
|---|---|
| 桌面壳 | Tauri |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus |
| 后端 | Python FastAPI Sidecar |
| 后端打包 | PyInstaller |
| 本地数据库 | SQLite |
| 可选数据库 | PostgreSQL |
| 图谱 | SQLite + NetworkX / Neo4j 可选 |
| 向量库 | FAISS / Chroma / Qdrant 可选 |
| 发布包 | AppImage、deb、tar.gz |
| 本地模型 | Ollama / vLLM |

---

## 3. Linux 客户端目录结构

```text
apps/desktop/
└── src-tauri/
    └── binaries/
        └── safeagent-backend-x86_64-unknown-linux-gnu
```

用户数据目录：

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

## 4. Linux 依赖要求

Ubuntu 示例：

```bash
sudo apt-get update
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev \
  build-essential \
  curl \
  wget \
  file \
  libxdo-dev \
  libssl-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev
```

---

## 5. Linux 后端 Sidecar

### 打包命令

```bash
pyinstaller safeagent_gov/desktop_boot.py \
  --name safeagent-backend-x86_64-unknown-linux-gnu \
  --onefile \
  --add-data "governance-skills-pack:governance-skills-pack" \
  --add-data "mcp-governance-pack:mcp-governance-pack" \
  --add-data "graphify-pack:graphify-pack" \
  --add-data "eval-pack:eval-pack"
```

---

## 6. Linux Tauri 配置

```json
{
  "productName": "SafeAgent-Gov",
  "version": "0.1.0",
  "identifier": "com.safeagent.gov",
  "bundle": {
    "active": true,
    "targets": ["appimage", "deb"],
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

## 7. Linux 运行模式

### 桌面模式

```text
Tauri App
+
Python Sidecar
+
SQLite
+
本地治理技能体系
```

### 服务模式

```text
FastAPI Server
+
Vue Web 控制台
+
Docker Compose
+
Redis / PostgreSQL / Qdrant
+
MCP Servers
```

Linux 是最适合服务模式的系统。

---

## 8. Linux Docker 增强部署

Linux 上可以提供完整 Docker Compose：

```text
safeagent-api
safeagent-web
safeagent-redis
safeagent-postgres
safeagent-qdrant
safeagent-ollama
safeagent-mcp-file
safeagent-mcp-email
safeagent-mcp-shell
```

启动：

```bash
docker compose up -d
```

该模式用于政企私有化部署和高并发测试。

---

## 9. Linux 安全原则

1. Shell MCP 默认阻断；
2. 不允许真实执行删除系统文件；
3. File MCP 默认限制在工作目录；
4. 需要明确授权后才能访问外部路径；
5. 数据库写入默认审批；
6. Docker 模式中高危 MCP 应独立容器隔离；
7. 所有工具调用写入审计；
8. 默认不上传敏感数据到云端模型。

---

## 10. Linux 构建命令

```bash
pnpm install
uv sync
pyinstaller safeagent_gov/desktop_boot.py --name safeagent-backend-x86_64-unknown-linux-gnu --onefile
pnpm tauri build
```

产物目录：

```text
apps/desktop/src-tauri/target/release/bundle/
├── appimage/
└── deb/
```

---

## 11. Linux 发布包

```text
release/linux/
├── SafeAgent-Gov_0.1.0_amd64.AppImage
├── SafeAgent-Gov_0.1.0_amd64.deb
└── safeagent-gov-linux-x64-v0.1.0.tar.gz
```

---

## 12. Linux 测试清单

| 测试项 | 目标 |
|---|---|
| AppImage 启动 | 无安装直接启动 |
| deb 安装 | 可通过 dpkg 安装 |
| Sidecar 启动 | Python 后端自动运行 |
| Docker 模式 | docker compose 可启动 |
| MCP 隔离 | 高危 MCP 可独立容器 |
| Graphify 构建 | 能生成能力图谱 |
| Eval 评测 | 能生成评测报告 |
| 服务模式 | 可运行 FastAPI + Web 控制台 |

---

## 13. Linux GitHub Actions 构建

```yaml
runs-on: ubuntu-latest

steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-node@v4
    with:
      node-version: 20
  - uses: pnpm/action-setup@v4
    with:
      version: 9
  - uses: actions/setup-python@v5
    with:
      python-version: "3.11"
  - uses: dtolnay/rust-toolchain@stable

  - name: Install Linux Dependencies
    run: |
      sudo apt-get update
      sudo apt-get install -y \
        libwebkit2gtk-4.1-dev \
        build-essential \
        curl \
        wget \
        file \
        libxdo-dev \
        libssl-dev \
        libayatana-appindicator3-dev \
        librsvg2-dev

  - name: Build
    run: |
      pnpm install
      uv sync
      pyinstaller safeagent_gov/desktop_boot.py --name safeagent-backend-x86_64-unknown-linux-gnu --onefile
      pnpm tauri build
```

---

## 14. Linux 开发结论

Linux 客户端适合两个方向：

```text
桌面端：面向开发者和评测人员
服务端：面向政企私有化部署
```

相比 macOS 和 Windows，Linux 端应重点突出：

```text
Docker 部署
服务模式
高并发测试
MCP 容器隔离
私有化模型接入
```
