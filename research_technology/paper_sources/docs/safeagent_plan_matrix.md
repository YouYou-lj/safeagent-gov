# `safeagent-gov_plan.md` 技术完成度矩阵

本矩阵以当前源码、可运行命令和生成结果为证据，不把设计文字、历史进度或“可以展示”当作完成证明。
状态含义：`完成` 为当前代码与测试直接证明；`部分完成` 为已有安全子集但未达到主计划终态；`未实现` 为
权威文件树或 API 中没有对应实现。

## 总体与核心模块

| 主计划章节 | 核心要求 | 当前权威证据 | 状态 | 下一工程门禁 |
|---|---|---|---|---|
| 1、3 | 输入检测、Agent、Skill、MCP、多模型、审计、评测全闭环 | I1— I4、Graphify/SafeRouter、Skill Runtime、Model Gateway、Agent、MCP、审计和评测已进入同一 trace | 完成（机制集） | 增加外部模型真实租户与开放任务质量验证 |
| 4.2—4.4 | 标准 Skill/MCP 目录与先检测后执行 | `skills/`、`mcp/`、统一 Skill Executor、MCP-Guard 能力票据和 TraceAudit | 完成（安全核心） | 接入 Agent 主流程后禁止直接导入 Skill 内部实现 |
| 4.5.1 | 六类强制安全 Skill | PromptShield、MCPGuard、SkillScan、TraceAudit、SensitiveData、Compliance 均有独立标准包、文件化策略和可信适配器 | 完成 | 扩展外部 PII 语料和行业合规规则，不把规则集宣称为法律认证 |
| 4.5.3—4.5.4 | Skill Registry、统一 Executor、超时/重试/降级/审计/指标 | `safeagent_gov/skill_runtime/` 与 `/api/skills/*` 已覆盖六个强制安全 Skill；Agent 按实际触发阶段计算 expected/completed | 完成（核心执行面） | 补 routed 业务 Skill 的降级评测 |
| 5.2—5.4 | SafeRouter 结构化拆解、多子智能体、并行组、聚合裁决 | 严格 DAG、真实分析 handler、有界 fan-out/fan-in、Risk Aggregator、Audit fan-in 和 `/api/agent/run` 已接入 | 完成（机制集） | 增加外部真实任务意图与业务子智能体泛化评测 |
| 5.5 | Vue 3/Vite/TS 管理控制台九个页面 | `frontend-vue/` 已实现计划九页并扩展 Graphify、系统治理与统一安全检测台，共十二页；Pinia、Router、Axios、Element Plus 按需加载和 lockfile 门禁已验证 | 完成 | 增加浏览器 E2E、无障碍和真实 OIDC/BFF 验收 |
| 6 | 队列、Worker Pool、优先级、舱壁、背压、SSE 和 1000 任务 | 进程内门禁保留；Compose 默认使用 Redis/Dramatiq 三池 Worker、ZSET 优先级、outbox、租约恢复、持久幂等与死信；1000 任务、Worker `SIGKILL` 和 AOF 重启均有可复算结果 | 完成（单节点分布式机制） | 扩展 Redis HA、多节点 Worker 和长时混合压力，不声称 exactly-once |
| 7 | OpenAI Responses、Anthropic、Gemini、Azure、Bedrock、Vertex、Ollama、vLLM | `safeagent_gov/model_gateway/`、13 个无密钥画像、10 类协议适配、成本/回退/缓存/熔断、Agent 主链与离线评测 | 完成（协议机制） | 配置真实账号/私有服务后分别做供应商联调，不用 mock 冒充认证 |
| 8 | MCP 注册、ToolGuard 强制、审批和工具策略 | `mcp/servers` 九项 capability、版本化策略、能力票据、审批与失败关闭 | 完成 | 保持 Graphify `guards/governed_by` 健康门禁 |
| 9 | 十类测试、路由/模型/并发指标和权威安全映射 | 安全、供应链、审计、四场景、Router、Model Gateway、1000 任务与工程韧性已有可复算结果 | 完成（随仓库机制集） | 增加外部数据、真实模型和多进程压力分布 |
| 10 | 十个核心 API | Agent、Router、Skill、MCP Call、Model Chat、审计、评测和审批路径均已注册；`/api/mcp/call` 使用服务端身份、单步任务图和一次性票据 | 完成 | 保持 OpenAPI 契约与鉴权回归 |
| 11 | task/skill/mcp/sub-agent/model 五类日志表 | `task_trace`、`skill_execution_log`、`mcp_tool_log`、`sub_agent_log`、`model_call_log` 为只读 SQLite View，统一投影签名事件链 | 完成（单一真相源） | 生产可迁移物化视图，但不得绕过 TraceAudit 写入 |
| 12—13 | 目标目录和四阶段路线 | 安全 MVP、多路由、Model Gateway、Vue 控制台、1000 任务及 Redis/Dramatiq 多进程恢复门禁完成 | 完成（机制集） | 保持证据复算并扩展生产 HA/外部生态 |

## Graphify-Gov

| 主计划章节 | 要求 | 当前权威证据 | 状态 | 剩余工作 |
|---|---|---|---|---|
| 16.5—16.8 | 节点、边、能力卡片、离线建图和在线检索 | `safeagent_gov/graphify/`、`configs/graphify_registry.yaml`；基础快照含 Skill/MCP/Agent/Policy/Model/Role/Risk/TestCase/DataSource，运行时投影签名 TracePattern | 完成 | 扩展开放世界数据来源与案例规模 |
| 16.12—16.13 | SQLite + NetworkX、节点/边表 | 固定 NetworkX 3.6.1、SQLite 原子快照与 MultiDiGraph 投影 | 完成 | 大规模图数据库属于 P3，不作为当前门禁 |
| 16.14 | build/update/search/node/path/stats/eval API | `backend/api/graphify_api.py` 另含 health 与签名 trace 学习接口 | 完成 | 保持 OpenAPI、身份和租户隔离回归 |
| 16.16—16.18 | 召回、路由、Token、延迟、过期与投毒治理 | `eval_graphify.py`、`tests/test_graphify.py`、健康检查 | 完成（3 条机制集） | 增加外部意图数据与 B1/B2 独立消融 |
| 16.15 | GraphifyCenter Vue 页面 | `frontend-vue/src/views/graphify-center/index.vue` 提供健康、统计、检索和可信重建操作 | 完成（控制面） | 增加交互式关系图渲染与大图性能测试 |
| 16.20 阶段二 | Graphify 接入 SafeRouter，限制候选执行集合 | Graphify 候选已进入 RouterPlan、分析子智能体和 Agent 主流程 | 完成（机制集） | 增加开放意图和跨进程压力评测 |
| 16.20 阶段三 | 向量召回、Token Budgeter、Model Gateway 成本 | 本地 384 维确定性稀疏向量与规则/场景联合召回；Token 预算进入 Router；Model Gateway 记录 Token/估算成本并生成 13 个模型节点 | 完成（离线机制） | 以外部语料做规则/向量独立消融，不把小型机制集宣称为泛化证明 |
| 16.20 阶段四 | 新组件扫描审批、节点签名、健康可视化 | 变化 Skill/MCP 先经 SkillScan，高风险能力需安全复核员；全部活动节点使用 TraceAudit 域分离签名，健康检查验证签名、审批、Guard/Policy 与陈旧状态 | 完成 | 生产将本地密钥迁移到 KMS/HSM 并实施四眼审批 |
| 16.20 阶段五 | TracePattern 历史路径学习 | 只消费完整性校验通过的签名 trace；trace 单次计数，成功样本≥2 且成功率≥80%才推荐，失败路径自动降权；`TracePattern --suggests_path--> capability` | 完成（安全阈值机制） | 增加长期路径漂移、延迟和 Token 成本加权评测 |

## 当前可复算证据

```bash
./scripts/setup_uv_env.sh
./scripts/uv_run.sh python -m ruff check --no-cache .
./scripts/uv_run.sh python -m mypy safeagent_gov/graphify research_technology/mcp agent_demo/adapters/external_agent.py integrations/reference_agent
./scripts/uv_run.sh python -m pytest -q tests/test_graphify.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_graphify.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_model_gateway.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_task_runtime.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_distributed_recovery.py
./scripts/uv_run.sh python scripts/check_markdown_links.py
./scripts/uv_run.sh python scripts/check_repository_index.py
```

Graphify 生成结果位于默认忽略的 `research_technology/benchmarks/results/graphify_eval_v1.json`；测试数据和结果不作为源码提交。
