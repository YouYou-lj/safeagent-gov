# I5 Graphify-Gov 能力知识图谱调度

Graphify-Gov 将仓库中真实存在的 Skill、MCP Tool、策略、子智能体、模型与任务意图转换为带版本和来源
哈希的能力图谱。运行时只向 Router 返回 Top-K 能力卡片和推荐路径，并由强制安全 Skill、`guards` 与
`governed_by` 边约束候选工具。

- 唯一源码：`safeagent_gov/graphify/`
- 注册表：`configs/graphify_registry.yaml`
- API：`backend/api/graphify_api.py`
- 测试：`tests/test_graphify.py`
- 评测：`benchmarks/runners/eval_graphify.py`
- 当前机制：规则、场景、本地 384 维稀疏向量、NetworkX 图遍历与签名 TracePattern 联合召回；组件变化
  受 SkillScan、人工复核和节点签名保护。未引入外部 embedding 服务，避免离线部署依赖与数据外发。

参见[可证伪假设](hypothesis.md)、[算法](algorithm.md)、[基线](baselines.md)和[证据索引](evidence.md)。
