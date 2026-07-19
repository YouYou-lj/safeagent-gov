# Vue 3 安全治理控制台

`frontend-vue/` 是默认 Web 控制面，面向主办方技术评审和政企安全运营人员。它只调用 FastAPI 公共接口，
不复制 Skill、MCP、路由、模型或审计业务逻辑，也不在浏览器中持有工具执行能力。

## 固定工具链

| 组件 | 固定版本/入口 |
|---|---|
| Node.js | 24.3.0；容器镜像同时固定多架构 SHA-256 |
| Vue / Vue Router / Pinia | 3.5.40 / 4.6.4 / 4.0.2 |
| Vite / TypeScript | 7.3.6 / 5.9.3 |
| Element Plus | 2.14.3，构建期按需导入 |
| 依赖真相源 | `frontend-vue/package-lock.json`，使用 `npm ci` |

`node_modules/`、`dist/`、覆盖率和 TypeScript 增量状态均被忽略，不能提交或进入 Docker 构建上下文。

## 页面与真实接口

| 页面 | 主要接口与证据 |
|---|---|
| 安全总览 | `/health`、Graphify、Task Runtime（运行模式、投递/恢复/死信）、Model Gateway 指标 |
| 安全检测台 | `/api/skill/scan`、`/api/mcp/scan`、`/api/agent/run`、`/api/model/test-connection|session/chat` |
| 智能体演练 | `/api/agent/run`，四场景完整安全编排 |
| Skill 中心 | `/api/skills/registry|metrics`，清单与内容哈希 |
| MCP 网关 | `/api/tool/check`，只裁决、不直接执行 |
| 能力图谱 | `/api/graphify/*`，健康、统计、检索与重建 |
| 路由监控 | `/api/router/plan`、`/api/tasks`，DAG 与隔离池状态 |
| 审批中心 | `/api/tool/pending|approve`，批准后仍需一次性票据恢复 |
| 审计追踪 | `/api/audit/{trace_id}` 与 `/verify`，事件视图和哈希链验真 |
| 模型网关 | `/api/model/*`，Provider、预算、降级、用量与不可信输出 |
| 安全评测 | `/api/eval/*`，只显示后端实际结果 |
| 系统治理 | `/api/auth/me`、策略灰度/发布/回滚和图谱健康 |

路由清单集中在 `src/router/routes/common.ts`，API 封装集中在 `src/api/`，Token 状态只位于 Pinia
`src/stores/auth.ts`。Axios 请求拦截器统一附加 Bearer 身份和处理错误；页面不得直接使用 `fetch` 或拼接鉴权逻辑。

## 本地运行与验证

先启动后端，再启动 Vite：

```bash
cd frontend-vue
npm ci --ignore-scripts --no-audit --no-fund
npm run dev
```

访问 <http://127.0.0.1:5173>，将后端签发的 Token 粘贴到右上角身份入口。Vite 仅把 `/api` 和 `/health`
代理到 loopback 8000；后端默认 CORS 只精确放行本地 5173/8501 来源，不接受通配符。

质量门禁：

```bash
cd frontend-vue
npm run lint
npm run typecheck
npm run test
npm run build
```

当前前端测试为 5 项，路由契约覆盖十二项页面；生产构建采用页面动态导入和 Element Plus 按需组件加载。CI 对 lockfile 执行
同样四条命令。

## 安全与生产边界

- 浏览器本地解析 JWT 只用于展示，授权始终来自后端验签、RBAC 和租户隔离。
- 原型将 Token 保存在当前浏览器 localStorage 以支持刷新恢复；生产环境应由 OIDC/BFF 使用 Secure、HttpOnly、
  SameSite Cookie，并配置短时访问令牌、刷新轮换和集中撤销。
- Model Gateway 输出固定为不可信数据；前端不能把模型文本解释成命令或能力票据。
- 安全检测台的临时 API Key 只保存在页面组件内存，切换 Provider 或卸载页面时清空，不进入 Pinia/localStorage。
- 审批页面不能直接恢复工具。实际恢复必须重新裁决并消费与主体、参数、策略版本绑定的一次性票据。
- 静态容器使用非 root、只读根文件系统、安全响应头与 CSP；`/api` 同源代理到 internal 网络后端。
- Vue 控制台是桌面端唯一前端；旧 Streamlit 原型已经移除。
