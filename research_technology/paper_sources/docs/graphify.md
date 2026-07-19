# Graphify-Gov 能力知识图谱

Graphify-Gov 是 `safeagent-gov_plan.md` 中的能力调度层。它不执行 Skill 或 MCP，也不授予工具权限；它只从
仓库权威 manifest、Python AST、版本化策略和注册表构建候选能力图，并把 Top-K 结果交给后续 Router。

## 安全边界

- 只读取固定的 `skills/`、`mcp/servers/`、`mcp/policies/versions/` 和 `configs/graphify_registry.yaml`。
- 使用 `yaml.safe_load` 和 Python AST，不导入、不执行被扫描组件。
- 符号链接、仓库外路径、重复工具、悬空 Skill/Agent/Model 引用和缺失 capability 函数均失败关闭。
- 每个 MCPTool 必须存在 `Skill --guards--> MCPTool --governed_by--> Policy` 链路；健康检查发现缺口即失败。
- Skill/MCP 首次仓库引导后，新增或内容变化必须先经 SkillScan 并由管理员或安全复核员批准；活动节点均有域分离签名。
- 应用重启只在空库时构建首个快照；已有快照即使来源已变化也不会自动替换，健康检查报告陈旧并等待显式复核更新。
- 历史路径只从 TraceAudit 完整性校验通过的 trace 学习，同一 trace 只计一次；至少 2 个成功样本且成功率不低于 80% 才影响推荐。
- 图谱推荐路径不是能力票据，真正执行仍须经过 MCP-Guard、策略裁决、审批和审计。

## 数据与实现

- 图节点/边契约：`safeagent_gov/graphify/contracts.py`
- 安全扫描器：`safeagent_gov/graphify/scanner.py`
- SQLite 原子快照与 NetworkX 投影：`safeagent_gov/graphify/store.py`
- 384 维确定性稀疏向量：`safeagent_gov/graphify/vector_index.py`
- 节点与 TracePattern 签名：`safeagent_gov/graphify/signing.py`
- 检索、健康与评测：`safeagent_gov/graphify/service.py`
- 版本化注册表：`configs/graphify_registry.yaml`

默认数据库位于已忽略的 `backend/data/graphify.db`，可通过 `SAFEAGENT_GRAPHIFY_DB_PATH` 指向独立路径。

## API

| 方法 | 路径 | 最低权限用途 |
|---|---|---|
| POST | `/api/graphify/build` | 管理员/安全复核员原子构建图谱 |
| POST | `/api/graphify/update` | 管理员/安全复核员增量复核并替换快照 |
| POST | `/api/graphify/search` | 鉴权用户按任务查询 Top-K 能力 |
| GET | `/api/graphify/node/{node_id}` | 查询节点及来源哈希 |
| POST | `/api/graphify/path/recommend` | 查询版本化推荐路径 |
| GET | `/api/graphify/stats` | 查询节点、边和关系规模 |
| GET | `/api/graphify/health` | 检查陈旧、孤立、Schema、Guard 和 Policy |
| POST | `/api/graphify/eval` | 运行本地机制回归集 |
| POST | `/api/graphify/learn/{trace_id}` | 管理员/安全复核员从同租户签名 trace 学习路径 |

构建和更新操作会写入 TraceAudit；所有接口均要求 Bearer 身份。

## 验证

```bash
./scripts/uv_run.sh python -m pytest -q tests/test_graphify.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_graphify.py
```

检索联合使用关键词规则、场景信号、本地稀疏向量、图关系与已达阈值的 TracePattern。基础图还包含五类
DataSource、版本化 TestCase 及 `validates` 关系。生成结果位于本地忽略目录
`research_technology/benchmarks/results/graphify_eval_v1.json`。当前小型数据只证明机制与安全门禁，
不代表开放世界意图路由泛化。
