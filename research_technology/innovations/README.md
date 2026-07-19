# 创新点索引

本目录用于让评审者快速验证创新，不存放重复业务代码。每项创新必须链接唯一源码、测试、数据、基线、消融和结果。

| 编号 | 创新点 | 核心技术证明 |
|---|---|---|
| I1 | [来源感知的跨输入攻击证据图](I1_provenance_risk_graph/README.md) | 对比单段规则/分类器，证明跨源与跨轮攻击召回提升 |
| I2 | [能力票据 + 污点传播 + 事务型审批](I2_taint_capability_guard/README.md) | 对比静态工具白名单，证明组合外泄攻击下降且审批可安全恢复 |
| I3 | [Skill 行为—权限一致性图](I3_behavior_permission_graph/README.md) | 对比关键词扫描，证明跨文件恶意行为和权限不一致检出提升 |
| I4 | [可验证审计链与任务回放](I4_verifiable_trace/README.md) | 证明内容、顺序、删除篡改均可检出，且任务决策可复现 |
| I5 | [Graphify-Gov 能力知识图谱](I5_graphify_capability_graph/README.md) | 证明 Top-K 能力检索降低上下文 Token，并强制补齐 Skill/Guard/Policy 治理路径 |

I1— I4 对应比赛四条核心安全技术线，I5 是 `safeagent-gov_plan.md` 增加的能力调度创新。每项创新均建立以下证据契约：

```text
README.md + hypothesis.md + algorithm.md + baselines.md + ablations.yaml + evidence.md
```

其中 `evidence.md` 明确区分当前基线、待实现机制和结果状态，避免将技术规划误标为已验证成果。
