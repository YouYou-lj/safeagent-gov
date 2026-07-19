# 技术要求与执行矩阵

| ID | 技术方向 | 当前状态 | 下一阶段核心实现 | 主要指标 | 独立目录 |
|---|---|---|---|---|---|
| T1 | 多源输入攻击识别与风险评估 | 机制、规模、四场景和通用外部工具型 Agent 真实进程联调完成 | 扩展商业异构 Agent 与外部多样性语料 | Recall ≥90%、FPR ≤8%、ASR ≤5% | `skills/promptshield-gov/`、`innovations/I1_*`、`integrations/reference_agent/` |
| T2 | 工具调用和任务执行约束 | 机制、200 条越权、灰度回滚、并发/故障压测完成 | 真实 MCP 服务身份和 mTLS 联调 | 高危控制 ≥95%、越权执行 0、组合 ASR ≤3% | `mcp/`、`skills/mcpguard-gov/`、`innovations/I2_*` |
| T3 | 插件/Skill/脚本供应链检测 | 50 恶意 + 50 正常闭环完成 | 阶段 7 扩展真实生态包和隔离动态分析 | 检出 ≥90%、FPR ≤10%、目标执行 0 | `skills/skillscan-gov/`、`innovations/I3_*` |
| T4 | 多维评测与审计溯源 | 五维、四场景、性能/故障注入和两套干净环境复现完成 | 外部可信时间与异构主机复测 | 完整/篡改检出 100%、回放 ≥95% | `research_technology/benchmarks/`、`research_technology/skills/traceaudit-gov/`、`research_technology/innovations/I4_*` |
| T5 | 多模型统一接入与安全治理 | 13 个 Provider 画像、10 类协议适配、Agent/Graphify/TraceAudit 闭环与离线机制评测完成 | 分供应商真实账号与私有推理服务联调 | 协议配置覆盖 100%、受限数据私有路由 100%、预算阻断 100%、危险执行 0 | `safeagent_gov/model_gateway/`、`configs/model_gateway.yaml` |
| T6 | 高并发异步任务治理 | Redis/Dramatiq 三池多进程舱壁、ZSET 优先级、outbox、背压、持久幂等、租约恢复、死信、SSE、1000 任务与真实强杀/AOF 门禁完成 | 扩展跨节点 Redis HA 与长时混合压力 | 1000 接收/终态、审计丢失 0、SIGKILL 恢复成功、AOF 重启持久、危险执行 0 | `safeagent_gov/task_runtime/`、`research_technology/benchmarks/runners/eval_task_runtime.py`、`research_technology/benchmarks/runners/eval_distributed_recovery.py` |
| T7 | 安全治理控制台 | Vue 3/Vite/TS 十二页控制面（含统一安全检测台）、真实 API、Pinia 身份、响应式布局、按需构建和容器门禁完成 | 浏览器 E2E、无障碍、真实 OIDC/BFF | lint/type/test/build 100% 通过、路由契约 12/12、浏览器不持有执行权、临时模型密钥不持久化 | `frontend-vue/`、`research_technology/reproducibility/docker/Dockerfile.frontend-vue` |

## 横向技术门禁

- [x] 所有模块使用统一公开 Schema，契约测试通过。
- [x] 所有创新有无防护、规则和完整系统基线。
- [x] 所有指标来自冻结留出/规模回归和版本化脚本；合成数据不宣称外部分布泛化。
- [x] 所有危险动作在隔离环境中验证，主机越权执行为 0。
- [x] 所有模块可独立测试，并能由应用层通过公开接口组合。
- [x] 干净 Python 3.11 容器可启动、运行四场景和完整 benchmark。
- [x] 全新 Python 3.14 venv 与固定 Python 3.11 验证镜像均完成 full benchmark、156 项测试和 89.48% 覆盖率门禁。
- [x] 独立外部工具型 Agent 经真实 loopback HTTP 运行四场景；错误令牌拒绝、服务不可用失败关闭、危险执行为 0。
- [x] Agent 默认经统一 Model Gateway 规划；模型输出无执行权，Provider、预算、回退、缓存、成本和审计契约可独立复算。
- [x] 1000 个进程内安全任务全部进入终态，四事件调度审计 4000/4000、丢失率 0；不将其解释为完整 LLM Agent 吞吐。
- [x] Redis/Dramatiq 真实 Worker `SIGKILL` 后 2 次投递、1 次租约恢复并成功终态；审计链有效，Redis AOF 重启后状态仍在，危险执行 0。
- [x] Vue 控制台十二项路由全部注册，TypeScript、ESLint、Vitest 和生产构建通过；旧 Streamlit 原型已移除。
