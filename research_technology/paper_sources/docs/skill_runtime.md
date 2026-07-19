# 统一 Skill Registry 与 Executor

Skill Runtime 是 Agent、Router 与六个强制安全 Skill 之间的统一执行边界。它负责加载治理元数据、校验参数、
限制并发、执行超时与有限重试、验证输出、写入 TraceAudit，并生成可查询的执行指标。Agent 不应绕过该边界
直接导入 Skill 内部实现。

## 安全边界

- Registry 只使用 `yaml.safe_load` 读取顶层 `skills/*/manifest.yaml`，并校验目录名、SemVer、入口文件、
  策略文件、输入输出、触发阶段和失败策略。
- manifest 的 `entrypoint` 只用于完整性核验和能力说明，不触发动态导入。Executor 只调用
  `safeagent_gov/skill_runtime/handlers.py` 中显式绑定的可信核心适配器。
- SkillScan 的 `package_path` 默认只能位于仓库 `skills/`；上传包仍使用 `/api/skill/scan` 的临时隔离路径，
  不能借通用执行 API 读取任意主机文件。
- API 身份只来自已验签 Bearer。客户端上下文中的 principal、tenant、role、trace 和 user 字段会被删除，
  MCPGuard 使用服务端注入的主体。
- 强制 Skill 的参数、触发阶段、超时、异常、输出契约或审计失败一律 `block`；只有明确声明为 routed 的
  非安全 Skill 才能使用 `continue_with_warning`。
- 超时后 Python 无法强制终止已经进入线程的同步函数，因此可信适配器必须保持检查型、幂等、无外部副作用；
  真正的工具副作用仍由 MCP 能力票据和 `guarded_tool_call` 控制。

## Manifest 治理字段

六个核心 manifest 已固定以下执行字段：

```yaml
category: security
execution_mode: mandatory
trigger_stages: [user_input]
required_inputs: [text]
required_outputs: [risk_level, risk_score, evidence, action]
timeout_seconds: 3
retries: 2
failure_policy: block
enabled: true
```

PromptShield 在用户输入、文档上传和 RAG 结果进入 Agent 前触发；MCPGuard 在每次工具调用前触发；
SkillScan 在 Skill/MCP 注册前触发；TraceAudit 在任务完成、阻断或审批后触发。
SensitiveData 在外部发送或数据导出前检测内容与标签并输出脱敏/审批/阻断；Compliance 在外发、导出或
政企流程动作前校验服务端主体角色、审批状态和不可省略的审计义务。两者均不持有工具能力票据。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/skills/registry` | 查询版本、触发、超时、失败策略和 manifest 哈希 |
| POST | `/api/skills/registry/reload` | 管理员/安全复核员原子重载本地 manifest，并写审计 trace |
| POST | `/api/skills/execute` | 在签名身份和统一执行器下运行指定 Skill |
| GET | `/api/skills/metrics` | 管理员/安全复核员/审计员查询进程内执行指标 |

执行示例：

```json
{
  "skill_name": "promptshield-gov",
  "trigger_stage": "user_input",
  "input_data": {"text": "请总结公开政策"},
  "context": {"scenario": "knowledge_service"}
}
```

响应包含 `success`、`status`、`skill_version`、`mandatory`、`attempts`、`parameter_complete`、
`audit_complete`、`latency_ms` 和结构化结果。安全裁决为 `block` 不代表 Skill 执行失败；只有运行或契约故障
才令 `success=false`。

## 指标语义

`/api/skills/metrics` 输出选择、实际、预期、启动、成功、失败、参数完整、错误触发、强制完成、审计失败、
最大并发和平均延迟。进程指标描述已提交给 Executor 的调用；`/api/agent/run` 另按每个任务的实际触发阶段
计算 `mandatory_skill_coverage` 与逐工具 `toolguard_coverage`，避免用累计进程指标掩盖单任务遗漏。

## 验证

```bash
./scripts/uv_run.sh python -m pytest -q tests/test_skill_runtime.py
./scripts/uv_run.sh python -m mypy safeagent_gov/skill_runtime backend/api/skill_runtime_api.py
./scripts/uv_run.sh python -m ruff check --no-cache safeagent_gov/skill_runtime backend/api/skill_runtime_api.py
```

测试覆盖 Registry 原子性与目录越界、参数与触发校验、自动补全、超时重试、并发舱壁、审计失败关闭、
API 鉴权、租户隔离、SkillScan 权限、MCP 身份覆盖、敏感信息无原文证据和合规角色防伪造。
