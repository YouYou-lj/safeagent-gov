# 桌面运行与可选研究复现

GovSafeAgent 的正式本地交付是 Tauri 桌面应用。应用自行启动 FastAPI Sidecar，使用本地 SQLite、
本地缓存和进程内任务运行时，不需要 Docker、Redis 或 Nginx。

## 本地 Python

本地固定使用 Python 3.11.12、uv 0.7.0 和 `uv.lock`；uv 管理的解释器、缓存与虚拟环境都留在仓库
已忽略目录。

```bash
./scripts/setup_uv_env.sh
./scripts/uv_run.sh uvicorn backend.main:app --reload --port 8000
```

另开终端启动默认 Vue 控制台：

```bash
cd frontend-vue
npm ci --ignore-scripts --no-audit --no-fund
npm run dev
```

业务 API 需要 Bearer 身份。生成本地管理员令牌：

```bash
./scripts/uv_run.sh python -m safeagent_gov.auth issue \
  --subject demo-admin --tenant demo-government --role admin --ttl 3600
```

访问 <http://127.0.0.1:5173>，将令牌粘贴到右上角身份入口。数据库默认写入
`backend/data/safeagent.db`，可用 `SAFEAGENT_DB_PATH` 指定。桌面发布模式则写入平台原生应用数据目录。

## 可选 Docker 研究复现

以下配置只用于论文中的分布式队列、容器隔离和恢复实验，不是桌面安装或启动步骤：

```bash
compose_file=research_technology/reproducibility/docker/docker-compose.yml
docker compose -f "$compose_file" up --build -d
docker compose -f "$compose_file" ps
```

访问 <http://127.0.0.1:8501>。默认拓扑只向 loopback 暴露无密钥 Nginx ingress；FastAPI、Vue、Redis 和
三类 Dramatiq Worker 只连接 internal 网络、默认不能访问公网。业务容器均使用非 root、只读根文件系统、
`cap_drop: ALL`、`no-new-privileges`、PID/CPU/内存限制和健康检查。

Vue 使用固定 Node 24.3.0 摘要镜像构建并通过 `npm ci` 验证 lockfile，运行阶段只保留固定摘要的非 root
Nginx 和静态产物。同源 `/api` 由前端容器代理到后端，浏览器不接触 internal 网络地址。

容器内签发令牌：

```bash
docker compose -f "$compose_file" exec backend python -m safeagent_gov.auth issue \
  --subject demo-admin --tenant demo-government --role admin --ttl 3600
```

`redis_data`、`audit_data`、`agent_output`、`eval_results` 四个命名卷分别保存 Redis AOF、SQLite/签名密钥、
受控模拟输出和 API 评测结果。Redis 固定为 8.2.3 镜像摘要，以 UID/GID `999:1000` 运行，不发布端口，使用
`appendonly=yes`、`appendfsync=everysec` 和 `noeviction`。停止服务不会删除卷：

```bash
docker compose -f "$compose_file" down
```

不要在需要保留研究证据时附加 `-v`。

## Redis/Dramatiq Worker

Compose 默认设置 `SAFEAGENT_TASK_RUNTIME_MODE=redis_dramatiq`，并按池隔离进程：

| 服务 | 队列 | 线程 | 用途 |
|---|---|---:|---|
| `worker-security` | `security` | 16 | PromptShield、SkillScan |
| `worker-agent` | `agent` | 8 | 完整 Agent |
| `worker-evaluation` | `evaluation` | 1 | 串行评测，避免共享结果竞争 |

Web 进程只写 Redis 状态和持久 outbox，不执行长任务。Worker 用 15 秒任务租约和心跳；失联租约由后端对账器
重投。Broker heartbeat 为 10 秒、Broker 死消息保留 7 天，应用永久失败另进入 `/api/tasks/dead-letter`。

验证真实进程恢复和 AOF：

```bash
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_distributed_recovery.py
```

脚本会强杀并重建 `worker-security`，随后重启 Redis；它不会删除命名卷，并在退出时恢复无故障注入 Worker。
交付语义是 at-least-once，生产 handler 必须幂等；跨机高可用需增加 Redis Sentinel/Cluster 或受管服务。

## API 调试与远端规划器

默认不暴露后端端口。需要本机 OpenAPI/curl 时显式叠加调试文件；端口只绑定 `127.0.0.1`：

```bash
docker compose \
  -f research_technology/reproducibility/docker/docker-compose.yml \
  -f research_technology/reproducibility/docker/docker-compose.debug.yml up -d
curl http://127.0.0.1:8000/health
```

远端 LLM/Dify 需要后端外联时，再显式叠加 egress 文件并注入对应 endpoint/API Key：

```bash
docker compose \
  -f research_technology/reproducibility/docker/docker-compose.yml \
  -f research_technology/reproducibility/docker/docker-compose.external.yml up -d
```

需要同时开放本机 API 和远端规划器时可叠加三个文件。`docker-compose.external.yml` 只提供网络能力，远端
请求仍受 HTTPS/loopback endpoint 校验、超时、响应上限、重试、熔断和严格 `AgentPlan` Schema 约束。

## 干净环境自动验证

一次性验证容器使用固定摘要的 Python 3.11 镜像，以非 root 身份顺序运行 compileall、全量 Ruff、Mypy、
文档/仓库索引、技术清单陈旧检查、85% 覆盖率整仓测试和评测：

```bash
docker compose -f "$compose_file" --profile verification run --rm verification
docker compose -f "$compose_file" --profile verification run --rm verification \
  python research_technology/reproducibility/scripts/container_verify.py --profile full
```

2026-07-18 两套干净环境实测：全新 Python 3.14 venv 与固定 Python 3.11 验证镜像均为 156 项测试、
89.48% 综合覆盖率通过；full profile 均覆盖 6 个数据集、4,904 条归一化逐样例结果和独立外部 Agent
的 12 条真实 HTTP 集成链路，五维门禁全部通过、失败样例 0、危险执行 0。性能延迟会随硬件和负载波动。

## 密钥、CORS 与限流

生产环境应分别注入至少 32 字节的独立随机值：

```text
SAFEAGENT_AUTH_SIGNING_SECRET
SAFEAGENT_AUDIT_SIGNING_SECRET
SAFEAGENT_CAPABILITY_SECRET
```

未注入时，三类密钥会在 `audit_data` 卷生成 mode `0600` 文件；它们不会进入镜像构建上下文。通过
`SAFEAGENT_CORS_ORIGINS` 配置精确来源、`SAFEAGENT_TRUSTED_HOSTS` 配置主机名；通配或空配置会失败启动。
限流由 `SAFEAGENT_API_RATE_LIMIT` 和 `SAFEAGENT_API_RATE_WINDOW_SECONDS` 控制。

## SQLite 一致性备份与恢复

备份使用 SQLite online backup API，复制前后运行 `PRAGMA integrity_check` 并输出 SHA-256：

```bash
docker compose -f "$compose_file" exec backend python scripts/backup_restore.py backup \
  --database /app/backend/data/safeagent.db \
  --output /app/backend/data/backups/safeagent-20260718.db
```

恢复命令只写新路径，目标存在时拒绝覆盖。验证新库后，再通过部署配置切换 `SAFEAGENT_DB_PATH`：

```bash
docker compose -f "$compose_file" exec backend python scripts/backup_restore.py restore \
  --backup /app/backend/data/backups/safeagent-20260718.db \
  --output /app/backend/data/restored/safeagent.db
```

## 生产化边界

- 将 SQLite 迁移到 PostgreSQL/受管数据库，并给审计事件增加 WORM、外部可信时间和 SIEM 告警。
- 将单节点 Redis AOF 升级为跨可用区受管 Redis/Sentinel/Cluster，并为 Redis URL 配置 TLS 与 ACL。
- 用政企 OIDC/IAM、KMS/HSM、集中式限流、TLS 反向代理和 egress allowlist 替换单机边界。
- 上传文件接入杀毒、内容拆弹、在线 SBOM/CVE 情报和独立动态分析沙箱。
- 远端任务正文出域前经过数据分级/DLP；通用外部 Agent 的 loopback 进程证据不等同于商业 Dify/OpenClaw 租户验收。
- `agent_demo/data/secret` 是阻断演示诱饵，不得放置真实敏感数据。

完整自审见 [Stage 7 工程安全自审](security_hardening.md)。
