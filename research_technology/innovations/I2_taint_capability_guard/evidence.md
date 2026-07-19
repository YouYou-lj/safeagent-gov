# 证据索引

| 类型 | 当前入口 | 状态 |
|---|---|---|
| Skill | `skills/mcpguard-gov/` | 标准包已建立 |
| 公共源码 | `mcp/gateway/`、`mcp/schemas/` | 已建立统一入口 |
| Server | `mcp/servers/` | 六类安全模拟 Server 已建立 |
| 策略 | `mcp/policies/versions/2.0.0.yaml`、`2.1.0.yaml` | 已版本化 |
| 测试 | `mcp/tests/`、`backend/tests/test_agent_audit.py` | 已覆盖票据越域/并发重放、审批全状态、TOCTOU、污点组合链与任务图异常 |
| 现有评测 | `eval/eval_tool_guard.py` | 冒烟基线 |
| 原型组合攻击数据 | `benchmarks/datasets/mcpguard_holdout_v1/` | 44 条、SHA-256 已冻结 |
| B0—B3 运行器 | `benchmarks/runners/eval_mcpguard.py` | 已生成逐样例、分类型和置信区间 |
| 版本化结果 | `benchmarks/results/mcpguard_holdout_v1.json` | B3 ASR 0、审批正确率 1.0、危险未授权执行 0、P95 约 1.6 ms |
| 规模与端到端证据 | `benchmarks/results/agentseceval_scale_v1.json`、`agentseceval_full_v1.json` | 200 工具越权 + 100 任务链，B3 ASR 0、危险执行 0 |

旧 `backend.core.mcp_guard` 与 `agent_demo.mcp_servers` 已按 [Stage 8 迁移记录](../../paper_sources/docs/migration_stage8.md)移除。

机制 holdout 的 B3 ASR 95% Wilson 区间上界约 9.64%；新增 200 条相关模板越权与 100 条端到端链用于规模回归。真实工具服务、外部 Agent 和高并发泛化仍需阶段 7 验证。
