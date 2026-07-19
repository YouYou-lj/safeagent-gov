# Agent 与外部规划器集成

SafeAgent-Gov 将外部工具型 Agent、LLM 和 Dify 限定为“不可信计划提供者”。它们只能返回 `AgentPlan`，不能直接调用
MCP Server、签发能力票据或恢复审批。计划的每个工具、参数、依赖边都会先做严格 Schema 校验，随后仍经过
PromptShield、任务图一致性、MCP 策略、能力票据、污点传播和 TraceAudit。

## 规划器模式

- `deterministic`：默认，无网络、无密钥，适合离线复现。
- `openai_compatible`：调用显式配置的 `/chat/completions`；配置或响应异常时失败关闭。
- `dify`：调用显式配置的 `/v1/workflows/run` blocking workflow；配置或响应异常时失败关闭。
- `external_agent`：调用版本化 `/v1/agent/plan` planning-only 契约；仅允许 HTTPS 或 loopback HTTP。
- `auto`：优先外部工具型 Agent，其次 OpenAI-compatible、Dify；远端运行异常时降级为确定性规划器并在审计中记录
  `fallback_from`，没有远端配置则直接离线运行。

OpenAI-compatible 配置：

```text
SAFEAGENT_PLANNER_MODE=openai_compatible
SAFEAGENT_LLM_ENDPOINT=https://llm.example/v1/chat/completions
SAFEAGENT_LLM_API_KEY=...
SAFEAGENT_LLM_MODEL=...
SAFEAGENT_LLM_TIMEOUT_SECONDS=15
```

Dify 配置：

```text
SAFEAGENT_PLANNER_MODE=dify
SAFEAGENT_DIFY_ENDPOINT=https://dify.example/v1/workflows/run
SAFEAGENT_DIFY_API_KEY=...
SAFEAGENT_DIFY_WORKFLOW=safeagent-planner
SAFEAGENT_DIFY_TIMEOUT_SECONDS=20
```

通用外部工具型 Agent 配置：

```text
SAFEAGENT_PLANNER_MODE=external_agent
SAFEAGENT_EXTERNAL_AGENT_ENDPOINT=https://agent.example/v1/agent/plan
SAFEAGENT_EXTERNAL_AGENT_TOKEN=...
SAFEAGENT_EXTERNAL_AGENT_NAME=expected-agent-name
SAFEAGENT_EXTERNAL_AGENT_TIMEOUT_SECONDS=15
```

仓库内的 `integrations/reference_agent/` 是独立工具型 Agent 参考应用。测试和统一评测会把它启动为真实
loopback HTTP 子进程，验证 Bearer 认证、请求关联、身份/版本、响应上限、服务不可用失败关闭和四场景链路。
该进程只产生计划，声明 `execution_authority=false`，且不导入 MCP Server 或工具处理器。

Dify workflow 必须输出名为 `plan` 的 JSON 对象/JSON 字符串，包含 `summary` 和 `steps`。远端请求只发送
任务、场景、角色、风险摘要、是否存在文档及工具 Schema，不发送文档正文、能力票据、审计签名密钥或
工具结果。生产环境仍需在数据分级策略中决定任务正文能否出域。

OpenAI-compatible 与 Dify 适配器当前使用注入式传输验证协议与失败边界，没有声称已连接某个商业租户。
通用 `external_agent` 已完成独立真实 HTTP 进程联调；这证明 vendor-neutral planning-only 接入边界，
不等同于 Dify/OpenClaw 官方协议认证。

远端传输使用 1 MB 响应上限和 60 秒绝对超时上限；仅 429、5xx、网络和超时类瞬态错误最多重试
`SAFEAGENT_PLANNER_MAX_ATTEMPTS`（默认 2）次。结构/工具/参数错误不重试。连续瞬态失败会打开进程内
熔断器，恢复窗口后只允许一个 half-open 探测；`auto` 模式可在审计留痕后回退到确定性规划器，显式远端
模式则停止任务且不执行工具。
