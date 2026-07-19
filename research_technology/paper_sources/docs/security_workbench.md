# 桌面安全检测工作台

`/workbench` 是 Skill、MCP 描述、多路由 Agent 与模型通信的统一测试入口。页面只组合既有公共 API，
不复制扫描器、路由器或工具执行逻辑，也不创建绕过 MCPGuard/TraceAudit 的第二条执行链。

## 四类检测

| 面板 | API | 安全边界 |
|---|---|---|
| Skill 检测 | `POST /api/skill/scan` | 静态 AST/行为图/SBOM；不导入目标代码 |
| MCP 描述检测 | `POST /api/mcp/scan` | JSON/YAML 有界解析；不启动 command，不访问 endpoint |
| Agent 路由测试 | `POST /api/agent/run` | 复用 Graphify、SafeRouter、强制 Skill、MCPGuard 与 Trace |
| 模型临时通信 | `POST /api/model/test-connection`、`/api/model/session/chat` | 请求级凭据、endpoint 允许列表、数据分级和不可信输出 |

MCP 检测识别内联秘密、本地进程启动、明文/私网 endpoint、描述提示注入、宽泛文件范围和高风险工具能力。
响应只返回字段路径、类别、评分和内容 SHA-256，不回显秘密值；解析过程有字符、alias、节点和深度上限。

模型临时通信支持 OpenAI、Anthropic、Gemini、Azure OpenAI、Bedrock、Vertex、DeepSeek、Qwen、Kimi、
Ollama 与 vLLM。公共厂商只能使用 HTTPS 官方主机与固定协议路径，本地服务只能使用 loopback；HTTP 重定向
被拒绝。公共远端不接受 confidential/restricted 数据。API Key 不写入环境变量、仓库、Pinia、localStorage、
响应或审计，Vue 组件切换 Provider 和卸载时会清空内存字段。

## 权威源码与验证

- 后端：`safeagent_gov/mcp_manifest.py`、`backend/api/mcp_api.py`、`backend/api/model_api.py`
- 前端：`frontend-vue/src/views/security-workbench/`、`frontend-vue/src/api/workbench/index.ts`
- 后端测试：`tests/test_mcp_manifest_scan.py`、`tests/test_ephemeral_model_api.py`
- 前端测试：`frontend-vue/tests/workbench.spec.ts`、`frontend-vue/tests/console.spec.ts`

```bash
./scripts/uv_run.sh python -m pytest -q tests/test_mcp_manifest_scan.py tests/test_ephemeral_model_api.py
cd frontend-vue && npm run lint && npm run typecheck && npm run test && npm run build
```

供应商协议使用注入传输完成离线测试，不把它表述为商业账号、组织租户或本机模型服务已联通。
