# 独立工具型 Agent 参考应用

该目录是一个独立 FastAPI 进程，用于验证 SafeAgent-Gov 对“OpenClaw 类或其他具备工具调用能力应用”的通用接入边界。它实现版本化的 planning-only HTTP 契约，不导入 MCP Server，不持有能力票据，也不执行工具。

SafeAgent 只向它发送经过最小化的场景、角色、输入风险摘要和工具 JSON Schema。返回计划被视为不可信输入，必须再次通过严格 `AgentPlan`、工具参数、任务图、MCP 策略、能力票据、审批与审计链。

这是一项真实 loopback HTTP 进程联调证据，不是 Dify/OpenClaw 官方协议实现，也不冒充第三方商业租户。Dify 适配器继续作为可选生产接入。

```bash
export SAFEAGENT_REFERENCE_AGENT_TOKEN='replace-with-at-least-16-chars'
uvicorn integrations.reference_agent.main:app --host 127.0.0.1 --port 8765
```

对应 SafeAgent 配置见 `docs/agent_integrations.md`，自动联调运行器为 `benchmarks/runners/eval_external_agent.py`。
