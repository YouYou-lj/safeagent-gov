# MCP-Guard-Gov 独立模块

`research_technology/mcp/` 是工具契约、策略、网关状态机和安全模拟 Server 的唯一实现位置。应用与 Agent 只能通过公开网关调用，不得绕过能力票据直接调用 Server。

## 公共接口

```python
from mcp.gateway import (
    check_tool_call,
    guarded_tool_call,
    issue_tool_capability,
    resume_approved_tool_call,
)
```

- `check_tool_call(...)`：规范化请求并执行版本化 RBAC、ABAC、参数和污点流向裁决。
- `issue_tool_capability(...)`：签发绑定主体、租户、任务、工具、精确参数、数据范围、标签、策略版本、有效期和次数的 HMAC 能力票据。
- `guarded_tool_call(...)`：校验并消费能力票据，验证任务图，记录审计事件；待审批请求只持久化不可变快照，不执行工具。
- `resume_approved_tool_call(...)`：重新运行当前策略，校验最终参数票据，并原子消费审批、票据和任务步骤。
- `mcp.schemas`：提供身份、来源、数据标签、任务图、能力授权、工具请求和策略裁决公共契约。

## 失败关闭边界

- 能力票据签名错误、过期、跨主体、跨租户、跨任务、越过参数/数据范围或重复使用时阻断。
- `public → internal → confidential → restricted → credential` 标签只保持或提升；摘要、编码、拼接不能降级。
- 未授权敏感数据流向浏览器、API 或邮件目标时进入审批或强制阻断。
- 审批支持申请、批准、脱敏批准、拒绝、超时、撤销、消费和幂等；强制 `block` 不生成审批，不能被人工覆盖。
- 任务图检测步骤重排、工具替换、参数拆分、循环调用和重放；状态存储异常时不执行。
- 审批与能力票据使用 SQLite 原子写锁保护并发消费；请求哈希用于检测 TOCTOU 变化。
- 工具策略由 `mcp/policies/versions/` 保存不可变 SemVer 快照；SQLite 控制面提供确定性灰度、提升、回滚、历史和缓存失效。
- 未注入部署密钥时，能力票据密钥持久化到数据库目录中的 mode-0600 文件；读取、格式或持久化失败时启动失败，而不是使用危险默认值。

## Server

| Server | 能力 | 原型安全边界 |
|---|---|---|
| file | read/write/delete | 映射仓库受控数据目录；写入仅限 output；删除不执行 |
| shell | shell_exec | 永不启动进程，策略默认阻断 |
| browser | browser_visit | 不发起网络请求，私网和非白名单地址阻断 |
| api | api_call | 不发起 HTTP 请求，仅返回模拟记录 |
| email | send_email | 不连接邮件系统，不真实投递 |
| database | query/write | 不连接数据库，写入不执行 |

各 Server 的 `manifest.yaml` 声明版本、能力和模拟边界；注册表、manifest 与策略表必须完全一致。

## 验证

```bash
python -m pytest research_technology/mcp/tests research_technology/skills/mcpguard-gov/tests -q
python research_technology/benchmarks/runners/eval_mcpguard.py
python research_technology/benchmarks/runners/eval_resilience.py
```

44 条合成原型留出集的完整 B3 结果为：攻击成功率 0、危险未授权执行数 0、审批状态正确率 1.0、安全任务完成率 1.0、P95 约 1.6 ms。该小样本只证明机制闭环，不代表真实业务泛化。

旧 MCP 转发层已在 Stage 8 技术冻结中移除，替代入口与迁移范围见 [兼容层清理记录](../paper_sources/docs/migration_stage8.md)。
