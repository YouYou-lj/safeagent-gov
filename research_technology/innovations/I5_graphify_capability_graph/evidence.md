# 证据索引

| 类型 | 入口 | 状态 |
|---|---|---|
| 图契约与服务 | `safeagent_gov/graphify/` | 已实现 |
| 版本化注册表 | `configs/graphify_registry.yaml` | 1.0.0 |
| FastAPI | `backend/api/graphify_api.py` | 构建、更新、检索、节点、路径、统计、健康、评测、签名 trace 学习 |
| 单元/契约测试 | `tests/test_graphify.py` | 原子更新、规则/向量检索、TestCase/DataSource、签名审批、TracePattern 去重/阈值/降权、API 鉴权 |
| 本地评测数据 | `benchmarks/datasets/graphify_cases_v1/` | 3 条机制回归，默认忽略提交 |
| 可复算运行器 | `benchmarks/runners/eval_graphify.py` | 失败时非零退出 |
| 生成结果 | `benchmarks/results/graphify_eval_v1.json` | 本地产物，默认忽略提交 |

结果必须由运行器生成，不能手工修改。当前机制集规模很小，所有指标只用于证明离线图谱链路和安全门禁，
不用于宣称真实用户意图分布上的泛化能力。
