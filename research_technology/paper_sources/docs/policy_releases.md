# 工具策略版本、灰度与回滚

MCP-Guard-Gov 的可发布策略位于 `mcp/policies/versions/`。文件名和文件内 `version` 都必须是 SemVer，且
必须精确声明注册表中的九种工具；版本缺失、声明不一致或工具集合漂移都会失败关闭。
旧 `mcp/policies/tool_policy.yaml` 快照已在 Stage 8 移除，避免稳定策略出现双来源。

发布状态和历史记录与审批/能力票据共用 SQLite 原子事务。状态包含稳定版本、灰度版本、灰度比例、上一稳定
版本、generation、操作者和时间。每次变更都会清除进程内策略缓存，并额外写入 TraceAudit 证据链。

## 控制面 API

以下 API 均要求 Bearer 身份。`status` 允许管理员、安全复核员、审计员读取；变更操作只允许管理员和安全
复核员。请求体、query 参数不能覆盖操作者身份。

```text
GET  /api/policy/tool/status
POST /api/policy/tool/canary   {"version":"2.1.0","rollout_percent":10}
POST /api/policy/tool/promote
POST /api/policy/tool/rollback
```

灰度分桶固定使用 `tenant_id + principal_id + task_id/trace_id` 的 SHA-256，因此同一任务不会在多次调用中
随机漂移。显式绑定的 `policy_version` 只能是当前稳定或灰度版本；审批恢复会重新执行当前策略并验证版本，
不能借旧审批绕过收紧后的规则。

当前原型的 2.1.0 灰度策略将 `staff` 的 `db_write` 从审批收紧为阻断，用于验证灰度、提升和回滚链路。
生产策略发布还应在仓库合并前增加签名制品和四眼审批；运行时控制面已经提供原子状态、历史与审计接口。
