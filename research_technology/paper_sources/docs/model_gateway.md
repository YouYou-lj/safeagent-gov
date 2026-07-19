# 统一 Model Gateway

Model Gateway 是 SafeAgent-Gov 的唯一多模型调用治理边界。它把供应商协议转换为同一请求/响应契约，并在
调用前执行能力、数据等级、上下文、延迟和费用筛选；调用中实施舱壁、超时、有限重试与熔断；调用后记录
Token、估算费用、回退链、输出摘要和审计事件。模型输出始终标记为 `output_trusted=false`，不具有工具执行权。

## 组件边界

- `configs/model_gateway.yaml`：无密钥 Provider 画像、路由规则、预算、缓存和并发上限；只保存凭据环境变量名。
- `safeagent_gov/model_gateway/contracts.py`：严格请求、Provider、使用量、响应和指标 Schema。
- `registry.py`：安全 YAML、符号链接拒绝、完整引用校验、原子快照与请求级无秘密内存注册表。
- `providers.py`：显式协议序列化/解析与 4 MiB 有界 JSON 传输，拒绝重定向，不动态导入配置代码。
- `service.py`：路由、租户/用户隔离缓存、服务端预算、超时重试、熔断回退、舱壁、审计和指标。
- `agent_demo/planners/model_gateway.py`：将模型输出限制为 planning-only JSON，再经工具白名单、参数 Schema 和
  DAG 校验生成 `AgentPlan`。
- `backend/api/model_api.py`：Bearer 身份、租户隔离、Provider 控制面、统一 chat 与指标 API。

Graphify 从同一份注册表生成 13 个 `ModelProvider` 节点，但 API 能力卡不包含 endpoint 或凭据变量名。

## 协议与证据边界

| 协议族 | 配置画像 | 本地验证 | 当前声明 |
|---|---|---|---|
| Internal | 确定性离线 Provider | 真实执行、Agent 主链 | 已验证离线基线 |
| OpenAI Chat Completions | OpenAI、DeepSeek、Qwen、Kimi | 注入传输序列化/解析 | 未声明商业账号实测 |
| OpenAI Responses | OpenAI | 注入传输序列化/解析 | 未声明商业账号实测 |
| Anthropic Messages | Claude | 注入传输序列化/解析 | 未声明商业账号实测 |
| Gemini generateContent | Gemini | 注入传输序列化/解析 | 未声明商业账号实测 |
| Azure OpenAI | 政企云部署 | 注入传输序列化/解析 | 未声明 Azure 租户实测 |
| AWS Bedrock | Bedrock Runtime | 注入传输序列化/解析 | 未声明 AWS 账号实测 |
| Vertex AI | Google Cloud | 注入传输序列化/解析 | 未声明 GCP 项目实测 |
| Ollama Chat | 本地模型 | 注入传输序列化/解析 | 未声明本机模型服务已部署 |
| vLLM OpenAI-compatible | 私有模型 | 注入传输序列化/解析 | 未声明私有推理集群实测 |

远端画像默认全部 `enabled=false`。启用时由运维人员修改受控配置并设置对应环境变量；密钥不得写入 YAML、
请求体、Graphify 元数据、审计事件或技术清单。明文 HTTP 只允许 `127.0.0.1/localhost` 私有 Provider。

## 路由与失败语义

1. `task_type` 选择候选序列，显式 `requested_provider` 只能在服务端已注册、已启用的画像内生效。
2. `restricted` 数据强制使用 `private_deployment=true`；调用者不能降低该约束。
3. 所需能力、上下文和输出上限、规则最大延迟、服务端费用上限任一不满足时排除候选。
4. 只重试超时、网络、429 和 5xx 等暂态错误；无效 JSON/Schema 不在同一 Provider 上重试。
5. 熔断打开后跳过 Provider，并按配置顺序回退；审计不可用或实现出现未知异常时立即失败关闭。
6. 缓存键绑定注册表摘要、租户、用户和完整规范化请求；命中缓存仍写独立 trace，费用增量为 0。

Agent 默认 `planner_mode=model_gateway`，离线配置选择确定性 Provider。远端模型只返回计划，不会获得能力票据、
签名密钥、MCP handler 或直接工具通道；最终工具调用仍由 Skill Executor、MCPGuard 和能力票据裁决。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/model/providers` | 返回无 endpoint/凭据的 Provider 能力摘要 |
| POST | `/api/model/providers/reload` | 管理员/安全复核员重载受控注册表并审计 |
| POST | `/api/model/chat` | 统一模型调用；身份和租户只取自 Bearer |
| POST | `/api/model/test-connection` | 使用一次性内存凭据发送固定最小测试消息 |
| POST | `/api/model/session/chat` | 临时受治理会话；厂商域名/路径或本机回环严格允许列表 |
| GET | `/api/model/metrics` | 查询调用、回退、缓存、并发、Token、费用和熔断状态 |

临时会话不修改进程环境变量或受控 YAML。API Key 只注入请求级 `ProtocolProvider`，不进入注册表摘要、响应、
审计或技术清单；公共远端拒绝机密/受限数据，Ollama/vLLM 只允许 loopback，云端只允许已知厂商主机与协议路径。

## 验证

```bash
./scripts/uv_run.sh python -m pytest -q tests/test_model_gateway.py
./scripts/uv_run.sh python research_technology/benchmarks/runners/eval_model_gateway.py
./scripts/uv_run.sh python -m mypy safeagent_gov/model_gateway agent_demo/planners/model_gateway.py
```

离线机制评测覆盖 13 个画像/10 类协议配置、回退、身份隔离缓存、受限数据私有路由、零预算阻断、Agent
接入、审计事件和不可信输出标记。该结果验证网关机制，不等价于供应商兼容认证、模型质量或商业账号可用性。
