# 基线

| 配置 | 说明 | 主要问题 |
|---|---|---|
| B0 全仓上下文 | 每次把 manifest、Skill 文档和策略整体提供给 Router | Token 与延迟随组件数量线性增长 |
| B1 关键词注册表 | 只按意图关键词返回静态组件列表 | 无图关系、工具保护和可解释路径 |
| B2 能力图谱 | 图检索 Skill/MCP/Agent/Policy | 仍可能漏掉强制安全 Skill |
| B3 Graphify-Gov | B2 + 规则/本地向量融合 + 强制 Skill + Guard/Policy + 签名审批快照 + 可信 TracePattern | 当前完整机制 |

当前 `eval_graphify.py` 以完整仓库上下文 Token 数作为 B0 成本基线，并对 B3 的召回、路由、治理覆盖、
Token 降幅和延迟执行门禁；单元回归另验证零关键词语义改写、节点签名/审批、trace 去重、成功阈值与失败
降权。后续扩展需要增加外部意图数据和 B1/B2 逐样例对比。
