# SafeAgent-Gov 公共技术体系视图

`core/` 是跨平台规划视图，不是第二份源码。为满足主办方快速查看创新资产的要求，权威 Skill、MCP 和
创新证据仍保留在仓库顶层；本目录通过 `manifest.yaml` 把规划中的技术分类稳定映射到唯一实现。

| 分类 | 权威实现 |
|---|---|
| Skills | `skills/`、`safeagent_gov/skill_runtime/` |
| MCP | `mcp/` |
| Agents | `agent_demo/`、`safeagent_gov/router/` |
| Graphify | `safeagent_gov/graphify/` |
| Eval | `benchmarks/`、`eval/` |
| Audit | `skills/traceaudit-gov/`、`safeagent_gov/audit.py` |
| Model Gateway | `safeagent_gov/model_gateway/` |
| Configs | `configs/` |

平台代码不得复制以上实现。macOS、Windows、Linux 只从这些路径冻结同一 Sidecar。
