# GovSafeAgent 论文技术体系

本目录是安全技术、实验设计、评测证据和论文素材的唯一聚合入口。`desktop/`、`frontend-vue/`、
`backend/` 与 `safeagent_gov/` 负责产品运行；本目录负责解释、复现和论证产品所使用的核心安全机制。

除明确写成仓库根路径的命令外，各模块文档中的 `skills/`、`benchmarks/`、`evaluation/`、
`innovations/` 等技术路径均以本目录为基准。

## 目录导航

| 目录 | 论文用途 | 与桌面端关系 |
|---|---|---|
| [`skills/`](skills/README.md) | 六项安全 Skill 的算法、策略、示例、测试和基准 | Sidecar 运行时直接调用 |
| [`mcp/`](mcp/README.md) | MCP 能力票据、污点传播、审批、任务图和安全 Server | Sidecar 运行时直接调用 |
| [`innovations/`](innovations/README.md) | 五项创新的假设、算法、基线、消融与证据索引 | 仅论文与评审材料 |
| [`benchmarks/`](benchmarks/README.md) | AgentSecEval 数据契约、运行器、结果和失败集 | 部分数据由 Sidecar 演示使用 |
| [`evaluation/`](evaluation/) | 轻量安全评测套件 | 后端评测 API 使用 |
| [`datasets/`](datasets/) | 正常、攻击、越权、恶意文档与 Skill 样例 | 论文实验输入，不随发布包提交 |
| [`core/`](core/README.md) | 权威能力边界和唯一源码映射 | 质量审计使用 |
| [`evidence/`](evidence/README.md) | SBOM、技术冻结清单、示例报告与评测摘要 | 论文结果与可复现性证据 |
| [`paper_sources/`](paper_sources/README.md) | 技术文档、历史计划和项目演进记录 | 不参与桌面运行 |
| [`reproducibility/`](reproducibility/README.md) | 非桌面分布式/容器实验配置 | 可选研究复现，不是桌面依赖 |

## 兼容边界

根目录的 `skills/`、`mcp/`、`benchmarks/`、`eval/` 只是轻量 Python 兼容入口，确保已有导入、
第三方集成和桌面 Sidecar 不受目录整理影响。真实源码只维护在本目录，禁止复制第二份实现。

## 建议论文主线

1. I1 来源感知风险证据图：`innovations/I1_*` + `skills/promptshield-gov/`。
2. I2 污点—能力票据—事务审批：`innovations/I2_*` + `mcp/` + `skills/mcpguard-gov/`。
3. I3 行为—权限一致性图：`innovations/I3_*` + `skills/skillscan-gov/`。
4. I4 可验证审计与签名回放：`innovations/I4_*` + `skills/traceaudit-gov/`。
5. I5 Graphify 能力知识图谱：`innovations/I5_*` + `../safeagent_gov/graphify/`。
6. 实证部分：`benchmarks/`、`evaluation/`、`evidence/`。
