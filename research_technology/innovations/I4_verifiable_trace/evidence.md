# 证据索引

| 类型 | 当前入口 | 状态 |
|---|---|---|
| Skill | `skills/traceaudit-gov/` | 标准包已建立 |
| 事件与查询 | `skills/traceaudit-gov/src/audit.py` | 版本事件、原子追加、角色脱敏、留存和导出已实现 |
| 哈希与签名 | `skills/traceaudit-gov/src/integrity.py` | 规范化、事件链、trace anchor、HMAC 和迁移已实现 |
| 回放 | `skills/traceaudit-gov/src/replay.py` | 签名 bundle、策略快照、输入/工具裁决复算已实现 |
| Schema | `skills/traceaudit-gov/policies/audit_schema.json` | 已版本化 |
| 测试 | `skills/traceaudit-gov/tests/`、`backend/tests/test_agent_audit.py` | 篡改、并发、脱敏、回放和审计故障失败关闭已覆盖 |
| 现有评测 | `eval/eval_audit_completeness.py` | 完整性冒烟基线 |
| 篡改/回放数据 | `benchmarks/datasets/traceaudit_holdout_v1/` | 60 篡改 + 20 回放，SHA-256 已冻结 |
| B0—B3 运行器 | `benchmarks/runners/eval_traceaudit.py` | 已生成逐案例、分类型与置信区间 |
| 版本化结果 | `benchmarks/results/traceaudit_holdout_v1.json` | B3 完整/检出/回放/一致率 1.0，回放危险执行 0 |
| 五维统一证据 | `benchmarks/results/agentseceval_full_v1.json` | 合规门禁全部通过，100 条端到端 trace 完整率 1.0 |

本目录只索引证据；可复算结果和逐事件明细统一归档到 `benchmarks/results/`。

旧 `backend/core/audit_logger.py` 转发层已按 Stage 8 迁移记录移除，公开入口为 `safeagent_gov.audit`。

HMAC 只证明部署信任域内的真实性，密钥保护仍依赖主机；当前不宣称具备外部可信时间戳、HSM 或不可抵赖性。
