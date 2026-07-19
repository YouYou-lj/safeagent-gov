# GovSafeAgent 技术评审导航

从本页可直接定位四条核心安全创新、一项能力调度创新、唯一源码、测试和评测入口。`research_technology/innovations/` 只保存主张与证据索引，不复制实现。

## 四条核心技术线

| 编号 | 创新与证据 | 独立 Skill | 唯一实现/当前基线 | 测试与评测 |
|---|---|---|---|---|
| I1 | [来源感知风险证据图](research_technology/innovations/I1_provenance_risk_graph/README.md) | [PromptShield-Gov](research_technology/skills/promptshield-gov/README.md) | `research_technology/skills/promptshield-gov/src/detector.py` | `research_technology/skills/promptshield-gov/tests/`、`research_technology/evaluation/eval_prompt_shield.py` |
| I2 | [污点、能力票据与事务审批](research_technology/innovations/I2_taint_capability_guard/README.md) | [MCPGuard-Gov](research_technology/skills/mcpguard-gov/README.md) | `research_technology/mcp/gateway/`、`research_technology/mcp/schemas/`、`research_technology/mcp/servers/` | `research_technology/mcp/tests/`、`research_technology/benchmarks/runners/eval_mcpguard.py` |
| I3 | [行为—权限一致性图](research_technology/innovations/I3_behavior_permission_graph/README.md) | [SkillScan-Gov](research_technology/skills/skillscan-gov/README.md) | `research_technology/skills/skillscan-gov/src/advanced_scanner.py`、`analysis.py`、`dependencies.py` | `research_technology/skills/skillscan-gov/tests/`、`research_technology/benchmarks/runners/eval_skillscan.py` |
| I4 | [可验证审计与回放](research_technology/innovations/I4_verifiable_trace/README.md) | [TraceAudit-Gov](research_technology/skills/traceaudit-gov/README.md) | `research_technology/skills/traceaudit-gov/src/audit.py`、`integrity.py`、`replay.py` | `research_technology/skills/traceaudit-gov/tests/`、`research_technology/benchmarks/runners/eval_traceaudit.py` |

## 强制数据与合规治理 Skill

| Skill | 强制触发点 | 唯一实现与策略 | 测试 |
|---|---|---|---|
| [SensitiveData-Gov](research_technology/skills/sensitivedata-gov/README.md) | 外部发送、数据导出前 | `research_technology/skills/sensitivedata-gov/src/detector.py`、`research_technology/skills/sensitivedata-gov/policies/sensitive_data_rules.yaml` | `research_technology/skills/sensitivedata-gov/tests/`、`tests/test_agent_orchestration.py` |
| [Compliance-Gov](research_technology/skills/compliance-gov/README.md) | 政企流程、外发、导出前 | `research_technology/skills/compliance-gov/src/checker.py`、`research_technology/skills/compliance-gov/policies/compliance_rules.yaml` | `research_technology/skills/compliance-gov/tests/`、`tests/test_agent_orchestration.py` |

## 能力调度创新

| 编号 | 创新与证据 | 唯一实现 | API/配置 | 测试与评测 |
|---|---|---|---|---|
| I5 | [Graphify-Gov 能力知识图谱](research_technology/innovations/I5_graphify_capability_graph/README.md) | `safeagent_gov/graphify/` | `backend/api/graphify_api.py`、`configs/graphify_registry.yaml` | `tests/test_graphify.py`、`research_technology/benchmarks/runners/eval_graphify.py` |

“当前机制”与“尚需外部基础设施/开放数据验证”的边界由每项 `evidence.md` 明确记录。

## MCP 安全边界

- 公共裁决：`mcp.gateway.check_tool_call`
- 票据签发：`mcp.gateway.issue_tool_capability`
- 审计执行：`mcp.gateway.guarded_tool_call`
- 审批恢复：`mcp.gateway.resume_approved_tool_call`
- 共享契约：`research_technology/mcp/schemas/contracts.py`
- 版本化策略：`research_technology/mcp/policies/versions/`，稳定版本为 `2.0.0.yaml`
- 发布控制面：`research_technology/mcp/gateway/policy_releases.py`、[灰度/回滚说明](research_technology/paper_sources/docs/policy_releases.md)
- 六类模拟 Server：file、shell、browser、api、email、database
- 已移除旧路径与替代入口：[Stage 8 兼容层清理记录](research_technology/paper_sources/docs/migration_stage8.md)

## 公共契约

- 应用公共 API：`safeagent_gov/input_security.py`、`supply_chain.py`、`audit.py`
- 跨模块契约：`safeagent_gov/contracts.py`
- API 身份：`safeagent_gov/auth.py`、`backend/auth.py`
- 统一领域异常：`safeagent_gov/errors.py`
- 能力图谱契约与检索：`safeagent_gov/graphify/`
- 结构化路由与有界执行：`safeagent_gov/router/`、[SafeRouter 说明](research_technology/paper_sources/docs/safe_router.md)
- 统一 Skill 注册与执行：`safeagent_gov/skill_runtime/`、`backend/api/skill_runtime_api.py`、[Skill Runtime 说明](research_technology/paper_sources/docs/skill_runtime.md)
- 数据/合规公共适配器：`safeagent_gov/data_governance.py`（六类 Skill 均经显式可信绑定）
- 统一模型协议与治理：`safeagent_gov/model_gateway/`、`configs/model_gateway.yaml`、`backend/api/model_api.py`、[Model Gateway 说明](research_technology/paper_sources/docs/model_gateway.md)
- 本地/可选分布式任务调度：`safeagent_gov/task_runtime/`、`backend/api/task_api.py`、[Task Runtime 说明](research_technology/paper_sources/docs/task_runtime.md)
- 默认治理控制台：`frontend-vue/`、`frontend-vue/src/router/routes/common.ts`、[Vue 控制台说明](research_technology/paper_sources/docs/frontend_vue.md)
- 统一安全检测工作台：`frontend-vue/src/views/security-workbench/`、`safeagent_gov/mcp_manifest.py`、[工作台说明](research_technology/paper_sources/docs/security_workbench.md)
- 跨平台核心视图：`research_technology/core/manifest.yaml`（只映射权威实现，不复制顶层 Skill/MCP）

## 可运行入口

- 后端：`backend/main.py`
- 默认前端：`frontend-vue/src/main.ts`（Vue 3/Vite/TypeScript，十二项治理页面）
- Agent：`agent_demo/langgraph_agent/agent.py`
- SafeRouter 规划与 Agent 主流程：`backend/api/router_api.py`、`agent_demo/langgraph_agent/orchestrator.py`
- Skill Registry/Executor API：`backend/api/skill_runtime_api.py`（显式核心适配器、失败关闭、审计和指标）
- Model Gateway API：`backend/api/model_api.py`（13 个固定画像；另有请求内凭据连接测试与受治理临时会话）
- Task Runtime API：`backend/api/task_api.py`（桌面进程内三池；Redis/Dramatiq 仅用于可选复现实验）
- MCP 检测与兼容调用 API：`backend/api/mcp_api.py`（离线 manifest 检测；服务端身份、单步任务图、一次性票据、仅模拟执行）
- 外部规划器：`agent_demo/planners/`、`agent_demo/adapters/external_agent.py`、`agent_demo/adapters/dify.py`
- 独立工具型 Agent 参考应用：`integrations/reference_agent/`
- 真实进程联调结果：`research_technology/benchmarks/results/external_agent_integration_v1.json`
- 四场景目录：`agent_demo/scenarios/`、`research_technology/benchmarks/datasets/four_scenarios_v1/`
- 当前完整评测：`research_technology/benchmarks/runners/run_all.py --profile full`
- Graphify 独立评测：`research_technology/benchmarks/runners/eval_graphify.py`
- SafeRouter/Agent 集成评测：`research_technology/benchmarks/runners/eval_router.py`
- Model Gateway 离线机制评测：`research_technology/benchmarks/runners/eval_model_gateway.py`
- 1000 任务零丢失评测：`research_technology/benchmarks/runners/eval_task_runtime.py`
- Worker 强杀与 Redis AOF 恢复评测：`research_technology/benchmarks/runners/eval_distributed_recovery.py`
- 统一基准与五维结果：[research_technology/benchmarks/README.md](research_technology/benchmarks/README.md)、`research_technology/benchmarks/results/agentseceval_full_v1.json`
- 技术执行计划：[research_technology/paper_sources/plans/project_plans/task_plan.md](research_technology/paper_sources/plans/project_plans/task_plan.md)
- 主计划完成度矩阵：[research_technology/paper_sources/docs/safeagent_plan_matrix.md](research_technology/paper_sources/docs/safeagent_plan_matrix.md)
- 技术要求矩阵：[research_technology/paper_sources/docs/technical_requirements_matrix.md](research_technology/paper_sources/docs/technical_requirements_matrix.md)
- 威胁模型与攻击树：[research_technology/paper_sources/docs/threat_model.md](research_technology/paper_sources/docs/threat_model.md)
- 仓库治理：[research_technology/paper_sources/docs/repository_governance.md](research_technology/paper_sources/docs/repository_governance.md)
- 固定 uv/Python 环境：[research_technology/paper_sources/docs/environment.md](research_technology/paper_sources/docs/environment.md)
- macOS / Windows / Linux 客户端：[desktop/README.md](desktop/README.md)、[跨平台架构](research_technology/paper_sources/docs/cross_platform_architecture.md)
- 非商业源码可用许可：[OPEN_SOURCE_NOTICE.md](OPEN_SOURCE_NOTICE.md)、`LICENSE`
- Stage 8 迁移记录：[research_technology/paper_sources/docs/migration_stage8.md](research_technology/paper_sources/docs/migration_stage8.md)
- CycloneDX SBOM：[research_technology/evidence/technical/sbom.cdx.json](research_technology/evidence/technical/sbom.cdx.json)
- 技术版本清单：[research_technology/evidence/technical/technical_manifest.json](research_technology/evidence/technical/technical_manifest.json)

## 快速验证

```bash
./scripts/uv_run.sh python -m pytest -q
./scripts/uv_run.sh python research_technology/evaluation/run_all_eval.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_mcpguard.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_skillscan.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_traceaudit.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_graphify.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_model_gateway.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_task_runtime.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_distributed_recovery.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/run_all.py --profile full
cd frontend-vue && npm run lint && npm run typecheck && npm run test && npm run build
cd desktop && npm run sidecar:build && npm run sidecar:verify
./scripts/uv_run.sh python scripts/check_repository_index.py
```

结构、Skill manifest、五个创新证据包、MCP manifest/注册表、文档链接、评审路径和技术清单陈旧状态均由自动门禁检查。
