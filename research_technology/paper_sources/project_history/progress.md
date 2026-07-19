# 技术规划进度日志

## 2026-07-17：范围收敛与仓库治理设计

- **状态：** complete
- **已完成：**
  - 删除计划中的报名、邮件、报告、视频和提交管理内容。
  - 将下一阶段改为 8 个纯技术阶段：仓库治理、创新契约、输入防护、MCP、Skill 供应链、审计、评测、集成与冻结。
  - 明确顶层 `skills/`、`mcp/`、`innovations/` 独立目录和标准模块契约。
  - 为四条创新技术线设置定量指标、基线、消融和验收证据。
  - 建立仓库分支、提交、版本、CI、数据、依赖和证据生成规范。
- **创建/修改：**
  - `task_plan.md`
  - `findings.md`
  - `progress.md`
  - `PROJECT_MAP.md`
  - `skills/README.md`
  - `mcp/README.md`
  - `innovations/README.md`
  - `docs/technical_requirements_matrix.md`
  - `docs/repository_governance.md`
- **移除：**
  - `docs/competition_requirements_matrix.md`，由纯技术矩阵替代。

## 当前阶段

阶段 0—10 已完成；主计划技术项、Redis/Dramatiq 恢复、完整评测、全仓覆盖和前端质量门禁均已闭环。

## 2026-07-18：I1 来源适配与证据图第一版

- **状态：** in_progress
- 新增 `SourceType`、`SourceEnvelope` 与 `ContentChunk` 公共契约，来源和分段均使用稳定 SHA-256 标识。
- 在 `skills/promptshield-gov/src/sources.py` 实现用户、网页、PDF/Word/纯文本、RAG、记忆五类适配器；网页适配器不发起网络请求，文档适配器限制大小和页数并支持 OCR 文本回退。
- 在 `normalization.py` 实现 NFKC、HTML 实体、零宽/双向控制字符、控制字符、空白规范化，并记录编码混淆证据标记。
- 在 `provenance.py` 实现来源—分段—风险证据图、同会话时序边、派生边和跨分段/跨来源联合检测。
- `/api/risk/detect` 与 LangGraph Agent 已接入完整来源分析；旧 `detect_input_risk` 继续作为 B1 规则基线。
- 新增来源、分段、证据图、跨源攻击和 API/Agent 集成测试；回归结果为 **38 passed**。

## 2026-07-18：统一 Skill Registry/Executor

- **状态：** complete
- 已恢复阶段 10 现场并核验四个核心 manifest；确认执行治理元数据、统一适配器、运行指标与复数路径 `/api/skills/*` 尚未实现。
- 已固定安全边界：核心 Skill 使用显式适配器白名单；manifest 入口不触发动态导入；参数、权限、安全策略和审计错误失败关闭。
- 四个核心 manifest 已升级为 1.2.0，补齐类别、强制触发阶段、必填输入输出、超时、重试、失败策略和启用状态；Registry 使用 safe YAML、包内路径/符号链接校验和原子快照。
- 新增 `safeagent_gov/skill_runtime/`：显式核心适配器、参数自动补全、输出契约、有界并发、超时、仅瞬态重试、失败关闭、逐阶段审计与进程指标；不执行 manifest 声明的任意入口。
- 新增 `/api/skills/registry|registry/reload|execute|metrics`；签名身份覆盖客户端上下文，跨租户 trace 返回 404，SkillScan 通用执行路径限制在受控根目录。
- 定向回归覆盖四个真实核心适配器、原子重载、越界、参数、触发、并发、超时、重试、审计故障、角色和租户隔离；12 项相关测试通过。
- 全仓 170 项测试中的实现测试均通过，语句/分支综合覆盖率 **88.88%**；技术清单已按“Graphify 评测后生成”顺序刷新并通过最终一致性门禁。

## 2026-07-18：Graphify/SafeRouter 接入 Agent 主流程

- **状态：** complete
- LangGraph 主链升级为 `trace → PromptShield Runtime → Graphify/Router → Planner → 分析子智能体 DAG → MCP → TraceAudit Runtime`；路由或审计不可用时失败关闭。
- ToolRisk、Compliance、DocumentRisk、GovRAG、SkillScan、Audit 六类 handler 已绑定，SafeRouter 保持有界并发、优先级、超时、依赖和 Audit fan-in。
- 用户、文档和跨源融合均经统一 PromptShield；每个实际工具调用在能力票据前再次经统一 MCPGuard；任务完成、阻断或审批后经 TraceAudit，并返回逐任务强制覆盖率。
- 修复仅场景匹配导致专用意图误选的问题；零关键词稳定回落 general，供应链真实短语显式进入版本化注册表。
- 新增 5 条本地机制集和 `eval_router.py`：子智能体召回、意图准确率、Audit fan-in、强制 Skill、ToolGuard、trace 完整率均为 1.0，危险执行 0，平均延迟约 45.59 ms、P95 约 79.55 ms。
- 原 12 条四场景回归仍保持安全完成率、攻击保护率、预期状态准确率和 trace 完整率 1.0，危险执行 0。
- 全仓实现回归 174 项通过；刷新技术清单后为 **175 passed**，纳入 LangGraph Orchestrator 的语句/分支综合覆盖率 **88.84%**。

## 2026-07-18：统一 Model Gateway

- **状态：** complete
- 新增 `safeagent_gov/model_gateway/` 与 `configs/model_gateway.yaml`：13 个无密钥 Provider 画像覆盖 10 类协议，远端画像默认全部禁用。
- Registry 实施安全 YAML、符号链接拒绝、严格引用与原子快照；HTTP 只允许 HTTPS 或私有 loopback，响应上限为 4 MiB。
- Gateway 实施任务/能力/数据等级/上下文/延迟/服务端预算路由、租户与用户隔离缓存、有界并发、超时、仅暂态重试、熔断回退、Token/费用指标和审计失败关闭。
- 新增 `/api/model/providers|providers/reload|chat|metrics`；Bearer 是唯一身份来源，跨租户 trace 返回 404，公开 Provider 摘要不包含 endpoint 或凭据变量名。
- Agent 默认规划入口切换为 `model_gateway`；模型只产生 planning-only JSON，经工具白名单、参数 Schema 与 DAG 校验后才形成 `AgentPlan`，仍无 MCP 执行权。
- Graphify 从同一注册表生成 13 个模型节点；模型能力卡只暴露协议、部署类型、启用状态和能力，不复制连接信息。
- 新增协议、路由、预算、私有数据、缓存隔离、并发、熔断、审计、API 与 Agent 测试；相关回归 33 项通过。
- `eval_model_gateway.py` 离线机制评测通过：配置协议覆盖、回退、身份隔离缓存、受限数据私有路由、零预算阻断、Agent 接入、模型审计与不可信输出标记均为 1.0，危险执行 0；不声明商业账号实测。
- Graphify 复算后模型节点进入同一来源摘要，3 条机制集 Recall/覆盖/路由均为 1.0，Token 估算降幅约 96.89%，平均检索约 1.25 ms。
- Router 5 条机制集与四场景 12 条回归全部通过，危险执行为 0；全仓最终为 **191 passed**，语句/分支综合覆盖率 **87.22%**。

## 2026-07-18：有界异步 Task Runtime 与 1000 任务门禁

- **状态：** complete（该里程碑只验收单进程机制，随后已由 Redis/Dramatiq 里程碑扩展）
- 新增 `safeagent_gov/task_runtime/`：严格任务/身份/池/状态契约、有界优先级队列、三类舱壁 Worker、容量背压、主体级幂等、超时和仅瞬态重试。
- 默认 handler 显式绑定 PromptShield、完整 Agent、SkillScan 和 Eval；API payload 不能选择入口或伪造 tenant/actor/role。
- 新增 `/api/tasks/submit|{task_id}|{task_id}/events|metrics` 与租户列表；SSE 不发送原始 payload，Eval/SkillScan/Agent 场景保持角色门禁。
- 调度状态以审计确认为准：入队审计失败不启动，完成审计失败不宣称成功，背压拒绝也进入可查询终态并写 `final_output`。
- 定向回归覆盖优先级、最大并发、幂等、重试、超时、背压、审计故障、API 鉴权与租户隔离，7 项通过。
- `eval_task_runtime.py` 的 1000 任务门禁通过：1000 接收、1000 成功、失败/拒绝/丢失均为 0，4000/4000 调度审计事件，强制覆盖 1.0，最大并发 32，约 634 tasks/s，P95 约 1.53s。
- 本里程碑当时只声明单进程机制；后续分布式实现与真实恢复证据见本文末尾的 Redis/Dramatiq 记录。
- Vue 与技术清单变更后的全仓回归为 **195 passed**，综合语句/分支覆盖率 **86.83%**，高于 85% 门槛。

## 2026-07-18：Vue 3 安全治理控制台

- **状态：** complete
- 新增独立 `frontend-vue/`，固定 Node 24.3.0 与精确 npm lockfile；环境、构建产物、覆盖率和增量缓存均被忽略。
- Vue 3、Vite、TypeScript、Pinia、Vue Router、Axios、Element Plus/SCSS 组成十一页默认控制面，覆盖主计划九页并扩展 Graphify 和系统治理。
- 页面全部调用 FastAPI 公共接口；MCP 页只做策略检查、审批页只记录决定、模型页保持不可信输出，浏览器不持有工具能力票据或执行入口。
- Token 状态集中在 Pinia，Axios 统一附加 Bearer；浏览器解码只用于显示，服务端验签/RBAC/租户隔离是授权真相源。
- 响应式导航、加载/空/错误态、主题变量、按需组件加载和路由动态导入完成；最大入口 JS 从约 1,031 kB 降到约 299 kB。
- 前端实测 TypeScript 零错误、ESLint 零警告、Vitest 2/2、Vite 生产构建通过，npm audit 为 0 vulnerabilities。
- 默认 Compose 已切换非 root、只读 Vue 静态容器；旧 Streamlit 仅保留为显式 `legacy-ui` profile。CI 纳入 npm lockfile 与四项质量门禁。
- 固定摘要容器在干净 Alpine 中完成 `npm ci`、类型检查和生产构建；运行实测 UID/GID `101:101`，`/healthz` 返回 `ok`。

### 阶段 2 完成记录

- 新增版本化轻量特征分类器 0.1.0、B0—B3 级联模式和可选人工/LLM 复核钩子；复核异常保持 `require_approval`，不自动放行。
- 冻结 20 条 dev 阈值集和 34 条原型 holdout，均记录 SHA-256、用途和限制；长上下文攻击另由自动测试覆盖。
- 阈值曲线确认当前 `review=0.55` 在 dev 上 Recall 1.0、FPR 0；该结果只用于配置验证。
- 原型 holdout：B0 Recall 0，B1 Recall 0.2727，B2 Recall 0.9091，B3 Recall 1.0；B3 Precision 1.0、FPR 0、P95 约 0.13 ms。
- B3 Recall 95% Wilson 区间为 `[0.8513, 1.0]`，说明 34 条样本仍不足以支持最终泛化结论；大规模独立数据归阶段 6。
- 阶段 2 最终回归为 **47 passed**；`eval/run_all_eval.py` 与 B0—B3 runner 均成功生成结果。

### 阶段 3 完成记录

- `ToolRequest` 已升级为类型化 `GatewayContext`，统一用户/Agent/租户身份、任务、来源、数据标签、授权目标和策略版本；未知字段与跨租户请求失败关闭。
- 策略 2.0.0 已联合 RBAC、Agent 角色覆盖、参数约束和污点流向；Agent 按 `public → internal → confidential → restricted → credential` 保守传播标签。
- HMAC 能力票据绑定主体、租户、trace/task、工具、精确参数、数据范围、标签、策略版本、有效期和使用次数；SQLite 原子消费账本与并发测试证明单次票据只能成功一次。
- SQLite 审批状态机已覆盖申请、批准、脱敏批准、拒绝、超时、撤销、消费、幂等和恢复；恢复前重新裁决，强制 block 不可覆盖，请求哈希检测 TOCTOU。
- 任务图已检测步骤重排、工具替换、参数拆分、循环/重放；LangGraph Agent 在读取 `/data/approved` 后将输出提升为 confidential，未授权邮件外发进入审批。
- 44 条合成原型 holdout 的 B0/B1/B2/B3 ASR 分别为 1.0000/0.5556/0.3611/0；B3 安全任务完成率 1.0、审批状态正确率 1.0、危险未授权执行数 0、P95 约 1.57 ms。
- B3 ASR 95% Wilson 区间为 `[0, 0.0964]`；小样本只证明机制闭环，最终泛化仍由阶段 6 的至少 200 条工具越权样本验证。
- 阶段 3 最终全仓回归为 **71 passed**；静态编译检查通过，Ruff 未安装，因此本轮未声称 Ruff 门禁通过。

### 阶段 4 完成记录

- 原 token 扫描已移入 `src/baseline.py` 固定为 B1；公共入口切换到 `advanced_scanner.py` 的 B3 主路径。
- Python 使用标准库 AST；JavaScript/TypeScript 使用不执行代码的 tokenizer + 结构化语法树，均支持 import/require 别名和文件/行/API/符号证据。
- 行为图已建立 module/function/call/evidence/permission/dependency 节点，以及 calls、resolves_to、flows_to、requires、depends_on 边；跨文件样例能还原 `source.get_secret → payload → requests.post`。
- manifest 声明与实际 shell/network/file/persistence/dynamic 权限联合评分，并输出未声明、显式禁止和过度声明的最小权限建议。
- requirements、pyproject、package.json、package-lock 可生成最小 SBOM、许可证和依赖关系；固定快照 `2026.07.1-demo` 覆盖 CVE、恶意包、高能力依赖和拼写劫持。
- 输入加固已覆盖路径穿越、符号链接、设备文件、加密/嵌套 ZIP、压缩比、单文件/总大小、文件数、语法 token/深度和总扫描时限；测试确认目标代码执行数为 0。
- 50 恶意 + 50 正常冻结包的 B0/B1/B2/B3 Recall 为 0/0.40/0.60/1.00；B3 Precision 1.0、FPR 0、解析失败率 0、P95 约 1.63 ms。
- B3 Recall 95% Wilson 区间为 `[0.9287, 1.0]`，正常 FPR 区间为 `[0, 0.0713]`；真实生态泛化仍归阶段 6/7。
- 阶段 4 完成后的全仓回归为 **82 passed**。

### 阶段 5 完成记录

- `AuditEvent` 与 SQLite Schema 已扩展 sequence、事件/策略/模型/数据版本、actor、前哈希、事件哈希和签名；trace 保存事件数、链头和链头签名，能够检测尾部删除。
- 规范化 JSON 固定键序、Unicode 与非有限浮点处理；每个事件和 trace anchor 使用部署密钥 HMAC-SHA256 签名，记录 key ID。
- 旧数据库只在整条 trace 都没有哈希时迁移；部分缺失视为异常并进入 `audit_alerts`，不会被重新计算后掩盖篡改。
- 新事件追加前验证全链，SQLite `BEGIN IMMEDIATE` 保护并发序号；20 路并发测试保持连续单链。审计钩子失败时工具处理器执行数为 0。
- 存储层对 password/token/secret/cookie/capability ticket 和正文做脱敏或长度+SHA-256 摘要；admin/replayer、reviewer/auditor/operator、viewer 使用分级视图，并记录留存类型与到期日。
- 签名回放 bundle 冻结用户/文档输入、事件、策略文件内容/哈希、版本和模拟工具响应；回放复算输入与工具裁决，不调用任何工具。
- 60 条六类篡改 + 20 条回放 holdout 中，B3 字段完整、篡改检出、回放成功和报告一致率均为 1.0，回放危险执行数 0；验证 P95 约 0.28 ms、回放 P95 约 2.57 ms。
- 篡改检出 95% Wilson 区间 `[0.9398, 1.0]`，回放成功区间 `[0.8389, 1.0]`；HMAC 不替代外部可信时间戳/HSM。
- 阶段 5 完成后的全仓回归为 **92 passed**。

### 阶段 6 完成记录

- 新增 `agentseceval_scale_v1` 冻结合成规模集：300 正常输入、500 复杂输入攻击、200 工具越权和 100 端到端任务链；沿用独立 SkillScan 50 恶意 + 50 正常包，所有数据均有来源、许可、限制和逐文件 SHA-256。
- `run_all.py` 通过独立子进程复算 I1—I4 的 B0—B3 与规模回归，统一生成 4,892 条逐样例记录，并记录代码、策略、模型、数据、环境、随机种子、延迟和 95% Wilson 区间。
- 五维结果 Schema 已固定为内容安全、数据安全、执行安全、供应链和合规；全量结果 22/22 门禁通过，危险未授权执行、目标 Skill 执行和回放副作用均为 0。
- 规模回归 B3：内容 Recall/Precision 1.0、FPR/ASR 0；工具保护率 1.0、ASR 0；100 条端到端任务状态/审计一致率 1.0、危险执行 0、P95 约 11.1 ms。
- 统一消融收益：I1 Full 相比 Rules Recall +0.7273；I2 Full 相比静态策略保护率 +0.5556；I3 行为图相比关键词 Recall +0.60；I4 签名链相比仅版本事件篡改检出 +1.0。
- 失败样例只以 ID、数据哈希和失败类型进入 `benchmarks/failures/`，禁止改写冻结 holdout；当前完整系统失败数为 0。
- CI 已配置每次 push/PR 的 smoke benchmark 与每周 full benchmark；配置已落库，本地未冒充远程 CI 实际运行结果。
- 阶段 6 完成后的全仓回归为 **96 passed**，静态编译成功；Ruff 仍未安装在当前 `.venv`，未声称本地 Ruff 门禁通过。

### 阶段 7 工程闭环记录

- 新增共享 `AgentPlan`/`ProposedToolCall` 契约、确定性/OpenAI-compatible/Dify 规划器、严格工具参数与任务图校验；显式远端失败停止执行，`auto` 仅在审计留痕后离线回退。
- Dify blocking workflow 和 OpenAI-compatible 适配器均完成注入传输、非法响应、超时、重试与熔断测试；没有可用第三方租户/API Key，因此未宣称真实外部服务联调完成。
- 四场景目录固定政务办公、知识服务、流程办理、运维协同，每类各 1 条正常、单点攻击、组合攻击；12 条端到端场景状态/审计一致率 1.0，危险执行 0。
- API 已启用 HMAC Bearer、租户隔离、角色依赖、服务端身份覆盖和按身份限流；跨租户 trace 返回 404。鉴权、审计、能力票据三类密钥独立持久化为 mode-0600 文件。
- 工具策略 2.0.0/2.1.0 采用 SQLite 原子发布状态，支持确定性灰度、提升、回滚、generation、历史和缓存失效；不可用或非活动版本失败关闭。
- 工程基准测量 2,000 次串行策略、1,000 次 16 并发、2,000 次鉴权、CPU 时间与 tracemalloc 峰值；六类故障注入失败关闭率 1.0、危险执行 0。本机结果并发 P99 约 16.6 ms，容器 full 结果约 18.9 ms。
- 容器改为锁定 Python 3.11 依赖、非 root、只读根文件系统、drop ALL、no-new-privileges、资源上限和健康检查；后端/Streamlit 只连 internal 网络，单独无密钥 Nginx ingress 暴露 loopback 8501。
- 首次真实构建发现原 `numpy==2.5.1` 只支持 Python ≥3.12，已修正为 Python 3.11/Linux 可安装的 2.4.6；两张镜像内 `pip check` 均无依赖破损。
- 一次性验证容器执行 compileall、**121 passed**、smoke 804 条和 full 4,904 条归一化结果；full 的 6 个数据集与五维门禁全部通过，失败样例 0、危险执行 0。
- SQLite 在线备份/非覆盖恢复、完整性校验、SHA-256、CORS/Trusted Host、安全响应头和工程安全自审均已补齐。

### 阶段 8 技术冻结记录

- 全量 Ruff、Mypy 和 ResourceWarning 失败门禁均通过；新增审批/能力票据/策略边界故障测试后，全仓为 **149 passed**，`backend.core + mcp` 语句/分支综合覆盖率 **90.39%**，高于 85% 门槛。
- 运行依赖与验证工具分别固定在 `requirements.lock`、`requirements-dev.lock`；Python 与 Nginx 基础镜像固定 SHA-256，验证镜像与运行镜像分阶段构建，生产镜像不包含测试工具。
- 新增 CycloneDX 1.6 SBOM 和技术版本清单，覆盖 94 个锁定依赖、基础镜像、模型状态、2 个策略版本、7 套数据、关键结果与源码树哈希；CI 会拒绝陈旧清单。
- 新增 72 份 Markdown 链接检查和评审索引/包边界检查；四个创新、四个核心 Skill 与 MCP 目录契约有效，淘汰路径不得重新出现。
- 删除一个迭代期满的 `backend/core`、`agent_demo/mcp_servers`、LangGraph 工具转发和重复 `tool_policy.yaml`，唯一实现边界收敛到 `skills/`、`mcp/` 与 `safeagent_gov` 公共入口。
- 全新 Python 3.14 临时 venv 从两个锁文件安装且 `pip check` 通过；full profile 4,904 条结果、静态检查、清单检查与 149 项测试全部通过。
- 固定 Python 3.11 验证镜像同样通过 Ruff、Mypy、链接/索引、清单、149 项测试、90.39% 覆盖率和 full profile；6 个数据集、4,904 条结果五维门禁全部通过，危险执行与失败样例均为 0，容器并发策略 P99 为 19.611 ms。

### 阶段 0 实施记录

- 迁移前基线：`.venv/bin/python -m pytest -q` 为 **11 passed**。
- 当前依赖集中在 `backend.core.*`；Agent 直接导入 `agent_demo.mcp_servers.*`，尚未形成顶层 MCP 包边界。
- 当前 Skill 只有包装脚本和小写 `skill.md`，缺少 manifest、src/policies/tests/examples/benchmarks 标准结构。
- 当前没有 `pyproject.toml`、pre-commit 或 CI 质量配置。
- 已确定 MCP 迁移方式：顶层 `mcp/` 保存唯一实现，`backend/core/mcp_guard.py`、`agent_demo/mcp_servers/*` 和 `agent_demo/langgraph_agent/tools.py` 只保留兼容导入。
- 已确定策略归属：工具策略迁入 `mcp/policies/`；PromptShield 与 SkillScan 策略分别归入对应 Skill 的 `policies/`，中央加载器只做显式路由。
- 顶层 `mcp/` 已成为网关、策略、Schema、Server 注册表和模拟执行器的唯一实现位置。
- 已补齐 file、email、browser、shell、api、database 六类独立 Server 包及 manifest；API/数据库模拟器不联网、不连接数据库。
- `backend/core/mcp_guard.py`、`agent_demo/mcp_servers/*`、`agent_demo/langgraph_agent/tools.py` 已改为兼容转发。
- MCP 迁移后回归结果：**11 passed**，与迁移前一致。

### 阶段 0 完成记录

- 四个 Skill 已统一为 `SKILL.md + manifest + src/policies/tests/examples/benchmarks`，旧小写入口不再承载实现。
- PromptShield、SkillScan、TraceAudit 的唯一源码已迁入各自 `skills/*/src/`；`backend/core/*` 只保留兼容导入。
- MCP 网关、共享 Schema、策略、注册表和六类模拟 Server 的唯一实现位于顶层 `mcp/`。
- `safeagent_gov/` 提供应用公共接口、共享契约和统一领域异常；API、Agent 与评测不再跨目录导入 Skill/MCP 内部符号。
- 四个 `innovations/I*` 证据包均包含假设、算法、基线、消融和证据索引。
- 已增加 `pyproject.toml`、`requirements.lock`、pre-commit 和 GitHub Actions 质量门禁。
- 阶段 0 最终回归：**28 passed**；完整冒烟评测各项指标均为 1.0，结果仅代表随仓库小样本。

### 阶段 1 完成记录

- `docs/threat_model.md` 已覆盖五个信任域、T1—T8 威胁、数据流图、攻击目标树和失败关闭边界。
- `safeagent_gov/contracts.py` 已建立 `RiskEvidence`、`PolicyDecision`、`ToolRequest`、`ApprovalState`、`AuditEvent`。
- I1—I4 均已固定可证伪假设、B0—B3 基线、消融配置和失败判据。

### 外部工具型 Agent 真实进程联调完成记录

- 新增顶层 `integrations/reference_agent/`，以独立 FastAPI/uvicorn 子进程实现 vendor-neutral planning-only
  契约；该进程不导入 MCP/工具处理器，并声明 `execution_authority=false`。
- 新增 `ExternalAgentPlanner`：只允许 HTTPS 或 loopback HTTP，实施 Bearer、Agent 身份/版本、request_id
  关联、1 MB 响应上限、60 秒绝对超时上限和严格未知字段拒绝。
- 真实进程基准覆盖四类政企场景共 12 条链路：状态准确率 1.0、审计完整率 1.0、四场景通过率 1.0、
  危险执行 0；错误令牌被拒绝，服务不可用时在工具执行前失败关闭。
- 联调结果已加入 `run_all.py` 的强制门禁和技术清单；12 条重复集成链路单独列示，不重复计入
  4,904 条归一化独立统计结果。
- 当前主机回归为 **156 passed**；覆盖范围扩展到外部适配器和参考服务后，关键模块语句/分支综合
  覆盖率为 **89.48%**。OpenAI-compatible/Dify 仍明确标记为需配置、未声称商业租户实测。
- 全新 Python 3.14 venv 从两份精确锁文件安装且 `pip check` 无破损；固定 Python 3.11 验证镜像也已
  重建。两套环境均通过 Ruff、39 个 Mypy 源文件、链接/索引/清单、156 项测试和含外部 Agent 门禁的 full 基准。
- 最终 backend/frontend 镜像已重建并强制替换旧运行容器；backend、frontend、ingress 均为 healthy，
  仅 ingress 绑定 `127.0.0.1:8501`，backend 公网 DNS 探针继续失败，证明默认无外联边界未被新集成放宽。

## 下一步

1. 可选接入具备授权 endpoint/API Key 的商业 LLM、Dify 或 OpenClaw 实例，扩展异构协议与生态证据。
2. 接入政企 OIDC/KMS、真实 MCP 身份与 mTLS、外部可信时间戳及隔离动态分析。
3. 持续执行 smoke/full 回归，并保持技术清单、SBOM 和评审索引与源码同步。

## 2026-07-18：固定 uv 环境与源码许可治理

- **状态：** complete
- 固定 `.python-version=3.11.12`、`.uv-version=0.7.0`，使用项目内 `.uv-python/`、`.uv-cache/` 和 `.venv/`，未污染用户全局 Python 环境。
- 新增 `uv.lock`、`scripts/setup_uv_env.sh`、`scripts/uv_run.sh` 与 `docs/environment.md`；本地和 CI 统一以 frozen 锁文件运行。
- 精确锁定运行/开发直接依赖，最终环境安装 95 个兼容包，`uv pip check` 通过。
- `.gitignore` 与 `.dockerignore` 已排除环境、测试数据、Benchmark 结果、密钥、数据库、报告和本地技术产物。
- 新增 `LICENSE`、`OPEN_SOURCE_NOTICE.md`，明确非商业使用与定制许可、商业书面授权要求及第三方材料边界。
- Ruff、39 个 Mypy 源文件、CI YAML、74 份 Markdown 链接、仓库索引和技术清单检查通过；固定环境完整回归为 **156 passed**。
- 当前目录仍没有 `.git` 元数据，因此只准备忽略和治理规则，未擅自初始化仓库或改变任何跟踪状态。

## 2026-07-18：主计划复核与 Graphify-Gov 基础图谱

- **状态：** complete（基础图谱后续已扩展本地向量、签名审批、TestCase/DataSource 与 TracePattern）
- 完整读取 `safeagent-gov_plan.md` 2,318 行并开始按权威源码复核；确认 Vue 控制台、SafeRouter 并发、Graphify、统一 Skill Executor、Model Gateway 和高并发队列不能由现有四条安全创新结果代替。
- 新增版本化 Graphify 注册表，扫描现有 Skill/MCP manifest、MCP Server AST 和版本化策略；扫描器不导入或执行目标代码，越出仓库、符号链接、无效 Schema 和陈旧引用均失败关闭。
- 新增稳定能力节点/边契约、SQLite 原子快照、NetworkX 有向图检索、强制 Skill 补全、工具 Guard/Policy 健康检查、Token 估算与三案例评测。
- 新增 `/api/graphify/build|update|search|node|path/recommend|stats|health|eval` 鉴权接口，控制面变更写入 TraceAudit。
- NetworkX 依据官方稳定版固定为 3.6.1，已写入 `pyproject.toml`、`requirements.lock` 和 `uv.lock`；项目内环境现有 96 个兼容包。
- 首轮 Graphify 定向测试为 **4 passed**；静态检查发现的导入排序与一个可空类型推断正在修复。
- 新增 `docs/safeagent_plan_matrix.md`，逐章标记完成、部分完成和未实现；不再用历史安全创新结论覆盖 Vue、SafeRouter、Model Gateway、高并发队列等缺口。
- Graphify 实际构建 36 个节点、83 条边，健康检查通过；3 条机制集的 Skill/MCP/Policy Recall@K、路由准确率、强制 Skill 与 ToolGuard 覆盖均为 1.0，Token 估算降幅约 94.7%，平均检索约 1.15 ms。
- Graphify 活动工具策略改为注册表显式固定 `2.0.0`，与运行时 stable release 一致，不再假设最新文件即稳定版本。
- 新增 `safeagent_gov/router/`：严格 RouterPlan/SubTask/Result 契约、Graphify 候选映射、风险优先级截断、并行组、超时、依赖和 Audit fan-in。
- 新增有界 asyncio 执行器：NetworkX DAG 拓扑 generation、信号量舱壁、强制任务失败关闭、前置阻断跳过和审计失败提升为 critical block。
- 新增 `/api/router/plan`，签名身份覆盖客户端角色，计划写入 TraceAudit；明确当前只生成计划，尚未替换 `/api/agent/run`。
- SafeRouter 定向测试 **4 passed**；与 Graphify 合并为 **8 passed**，Ruff 与 11 个相关 Mypy 源文件通过。
- 新增后完整回归为 **164 passed**；按 `backend.core + external Agent + reference Agent + mcp + safeagent_gov`
  当前覆盖配置重新计算语句/分支综合覆盖率 **89.66%**，高于 85% 门槛。
- CI 已纳入 Graphify/Router 编译、类型和覆盖范围；本地忽略的 Graphify 机制数据不存在时明确跳过，不把
  私有测试数据作为源码提交前提。

## 验证

| 检查 | 预期 | 状态 |
|---|---|---|
| 技术计划不含报名/邮件/视频/提交事务 | 仅保留研发、评测、工程与仓库治理 | 通过 |
| 四项 PDF 技术方向均有执行阶段 | 输入、工具、供应链、评测审计全部覆盖 | 通过 |
| Skill/MCP/创新点独立顶层目录 | 根目录可直接定位 | 通过 |
| 每项创新有指标和验收 | 不以功能存在代替技术证明 | 通过 |

## 错误记录

| 错误 | 处理 |
|---|---|
| 旧计划混入非技术提交事项 | 按用户要求整体重写为纯技术计划 |
| 当前目录不是有效 Git 工作树 | 记录为阶段 0 技术治理任务，本轮不擅自初始化远程仓库 |
| 原锁文件的 `numpy==2.5.1` 不支持 Python 3.11 镜像 | 固定为 2.4.6，并用实际 Linux/aarch64 构建与 `pip check` 验证 |
| Docker internal 网络无法同时提供宿主入口；普通 bridge 在 Docker Desktop 仍可出网 | 业务容器只挂 internal 网络，新增无密钥/无业务卷的最小权限 ingress 单独连接 edge |
| ingress 健康检查的 `localhost` 解析到 IPv6 但 Nginx 仅监听 IPv4 | 健康目标改为 `127.0.0.1`，三项服务最终均为 healthy |
| 验证镜像首次重建时远端 wheel 实际字节与包索引声明哈希不一致 | pip 主动终止构建；未关闭校验，启用不进入镜像层的 BuildKit 缓存后重新下载，同一版本通过校验与 `pip check` |
| 非 root 验证容器无法在 `/app` 创建 Ruff/Mypy/coverage 缓存 | 不放宽目录权限；Ruff 禁用缓存，Mypy 与 coverage 临时状态定向到 `/tmp`，重建后全量门禁通过 |
| 主机沙箱禁止绑定 loopback 随机端口 | 在获得仅限 `127.0.0.1` 的执行授权后运行真实进程测试；未改成进程内 mock 绕过证据要求 |
| 固定环境首次完整测试使用的临时鉴权密钥只有 31 字节 | 安全门槛正确拒绝；改用超过 32 字节的独立临时密钥后，156 项测试全部通过 |
| Graphify 首轮 Ruff 检查发现 4 个导入顺序问题 | 使用项目固定 Ruff 版本执行机械排序，不手工扩大改动范围 |
| Graphify 首轮 Mypy 将循环变量复用推断为 `str`，随后赋值 `str | None` | 将查询结果改为语义明确的 `tool_risk_name`，消除作用域复用并保留空值判断 |
| Router API 初次补丁因 Ruff 已改变 `backend/main.py` 导入布局而无法匹配 | 读取当前文件后用精确上下文重放；失败补丁未产生部分写入 |
| SafeRouter 首轮 Mypy 将函数内复用的 `skill_ids` 先推断为列表、后赋值集合 | 将最终候选集合命名为 `retrieved_skill_ids`，避免跨分支变量类型漂移 |
| Graphify 结果与技术清单并行生成导致清单刚生成即陈旧，完整回归 163 通过、1 失败 | 固定证据流水线顺序为“先评测、后清单”，串行再生成并复跑完整测试 |
| Skill Runtime 首个跨多文件补丁的 manifest 更新块缺少合法边界 | 工具整体拒绝且未产生部分写入；拆分为异常、manifest、运行时与 API 小批次补丁后继续 |
| README/矩阵首个组合补丁误把 `rg` 输出前缀当作文件正文 | 工具整体拒绝且未写入；读取精确上下文后重放最小补丁 |
| 旧状态检索命令把反引号包裹的 API 路径交给 shell，触发一次无写入的路径执行错误 | 后续 shell 检索只使用安全引用或不含反引号的模式；未造成文件或外部状态变化 |
| PromptShield bundle 首个补丁假定了错误的 contracts 导入上下文 | 工具整体拒绝且未产生部分写入；读取当前 imports 后拆分重放 |
| Skill Runtime 完整覆盖率回归 169 通过、1 失败 | 唯一失败为技术清单正确识别新增 7 个源码/文档文件；先重算 Graphify，再串行生成 SBOM/清单后复跑，代码覆盖率为 88.88% |
| Agent Orchestrator 首轮 Mypy 发现动态分析字典推断为 `object`，且 TypedDict 未被接受为可变 dict | 为分析/风险结果增加明确类型，并在顺序回退边界显式复制为 dict；不放宽类型检查 |
| Agent API 新断言暴露零关键词任务被场景分误路由到 SkillScan 意图 | 场景分只增强已有关键词命中的专用意图；零关键词任务稳定回落 `general_task`，避免字典序伪路由 |
| 零关键词回退修复使 Graphify 供应链机制案例不再依赖旧场景分，暴露短语不连续 | 为注册表补充真实可解释短语 `新上传`、`可以上线`，保持专用意图必须有文本证据 |
| Orchestrator 扩大失败关闭捕获后留下两个未使用领域异常导入 | 删除失效导入并重新执行 Ruff/Mypy，不使用忽略规则 |
| Agent Orchestrator 完整覆盖率回归 174 通过、1 失败 | 唯一失败为 Router 数据/结果与新增源码使技术清单陈旧；评测已先复算，随后串行刷新清单 |
| Skill Runtime 首轮 Mypy 发现两个 `type: ignore` 已无必要 | 删除冗余忽略，不放宽类型门禁，随后重新检查 |
| Skill Runtime 首轮定向测试 3 项失败：合法安全结果的空 `evidence` 被当成缺失输出 | 将输入非空校验与输出字段存在性校验分离；输出允许合法空字符串但仍拒绝缺字段/`None` |
| Model Gateway 联动 Graphify 的首轮测试调用了不存在的 `GraphifyService.node` | 按既有公共边界改用 `GraphStore.get_node`；实现已正确生成 13 个模型能力节点，未新增重复服务接口 |
| Model Gateway 组合文档补丁两次假定了过期的 SafeRouter/README 行上下文 | 补丁均整体拒绝且无部分写入；按 `model_gateway.md`、README、Benchmark、API、SafeRouter 分文件读取并重放 |
| 扩展 Planner Mypy 范围后发现 factory 分支复用变量导致类型被固定为 OpenAI Planner | 按协议分支改用 `openai_planner`、`dify_planner`、`external_planner`，不添加类型忽略 |
| Vue 首轮类型检查认为 RouterRecord `meta` 可空 | 增加显式 RouteMeta 类型守卫，保留集中式路由并通过严格类型检查 |
| ESLint 10 加载 TypeScript 配置额外要求 `jiti` | 将配置改为原生 ESM `eslint.config.js`，不为配置解析引入额外运行依赖 |
| 首次 `vue-tsc -b` 把虚拟 Vue 产物写入源码目录，导致 2729 条 Lint 噪声 | 使用 build-clean 删除可确认生成物，并将 typecheck/build 永久改为 `--noEmit` |
| Element Plus 全量注册使主入口 JS 约 1031 kB | 改为构建期按需组件加载和页面动态导入，入口降至约 299 kB，全部质量门禁继续通过 |
| Vue Nginx 镜像首次以 UID 101 启动时尝试写 `/var/cache/nginx` | 将五类 Nginx 临时路径显式定向到容器 `/tmp`，不提升权限或放宽只读根文件系统 |

## 2026-07-18：Redis/Dramatiq 多进程任务恢复

- **状态：** complete
- 固定新增 Dramatiq 2.2.0、redis-py 7.4.1 与 fakeredis 2.36.1；uv 锁、本地 `.venv` 和 Linux 运行锁同步，`pip check` 通过。
- 新增 `RedisTaskStore`：任务记录、租户索引、主体级幂等键、ZSET 优先级队列、staging、持久 outbox、Worker 租约、终态、死信和跨进程指标均使用独立命名空间。
- 新增 `RedisDistributedDispatcher`：入队审计失败关闭、审计确认后原子激活、outbox 重投、staging 对账和过期租约恢复；本地测试仍使用兼容的进程内 Dispatcher。
- 新增三个 Dramatiq wake Actor 与独立 Worker Runtime；security/agent/evaluation 分别绑定独立队列和 16/8/1 线程，框架重试为 0，应用只有限重试暂态错误。
- Compose 固定 Redis 8.2.3 多架构摘要，以 UID/GID `999:1000`、internal-only、无端口、只读根、drop ALL 和 AOF everysec 运行；后端及三个 Worker 均健康。
- 新增 `/api/tasks/dead-letter`，`TaskRecord` 暴露投递、恢复、租约元数据，运行指标区分 `in_memory`/`redis_dramatiq` 并统计 recovered/dead-letter。
- 新增 fakeredis 并发幂等、优先级、背压、staging、租约恢复、死信、outbox、审计失败关闭、协调器断线存活、Actor 与 Compose 契约测试；相关 16 项检查通过。
- Linux/arm64 四张后端/Worker 镜像从精确锁文件干净构建，Dramatiq/redis-py 和全部既有依赖安装完成且无依赖破损。
- 普通真实容器任务 1 次投递成功，记录 4 个调度审计事件；修复协调器断线存活问题后，最终恢复门禁对 `worker-security` 发送 `SIGKILL`，15.702 秒接管，2 次投递、1 次恢复、运行时恢复增量 1、成功终态、审计链有效、危险执行 0。
- 恢复完成后等待 AOF fsync 并重启 Redis，同一 TaskRecord 仍可由鉴权 API 查询；结果写入 `benchmarks/results/distributed_recovery_v1.json`。
- Vue 类型契约和安全总览已显示运行模式、投递、恢复和死信；ESLint、TypeScript、2 项 Vitest 和生产构建通过，最大入口仍约 299 kB。
- 交付语义明确为 at-least-once，不声称跨 Redis/SQLite exactly-once；生产仍需幂等 handler、一次性能力票据、Redis TLS/ACL 与多节点 HA。

### 本阶段错误与处理

| 错误 | 处理 |
|---|---|
| 直接运行 `.venv/bin/pytest` 时脚本目录替代仓库根路径，导致 `skills` 包无法导入 | 统一改用固定解释器的 `python -m pytest`，未修改包边界或注入全局路径 |
| 首次恢复探针用 `python scripts/distributed_task_probe.py`，容器内无法导入项目包 | 改为 `python -m scripts.distributed_task_probe`；失败发生在任务提交和 Worker 强杀之前，finally 已恢复正常 Worker |
| 首次全仓回归的 3 个真实 loopback 测试被主机沙箱拒绝绑定端口 | 保留真实进程测试，最终以授权的 loopback 执行重跑，不改成进程内 mock |
| 首次全仓回归另有 1 项技术清单陈旧 | 按既定证据顺序先完成全部评测与文档，再生成 SBOM/清单并最终复跑 |
| 前端组合门禁误用了不存在的 `type-check` 脚本名 | 读取 `package.json` 后按权威脚本 `typecheck` 重跑，Lint/类型/测试/构建均通过 |
| 在第二次恢复评测重启 Redis 后，第三次强杀 Worker 的任务停留在 `RUNNING` 并超时 | 定位为协调循环捕获 Redis 异常后又写 Redis 失败指标，二次异常逃逸并永久终止循环；指标写入改为 best-effort 双层保护，新增“Redis 与指标同时失败后循环仍存活并恢复租约”的回归测试 |

## 2026-07-18：主计划剩余技术项闭环

- **状态：** complete
- 新增 SensitiveData-Gov、Compliance-Gov 两个标准独立 Skill 包及文件化策略；六类治理 Skill 由统一
  Registry/Executor 绑定，外部发送、数据导出和流程动作前强制执行，敏感标签向合规决策传播。
- 新增 `/api/mcp/call`：Bearer 主体是唯一身份来源，服务端固定内部数据标签、生成单步任务图并只签发一次性
  能力票据；block/require_approval 不执行，允许路径只调用已注册模拟器。
- `task_trace`、`skill_execution_log`、`mcp_tool_log`、`sub_agent_log`、`model_call_log` 已实现为签名
  TraceAudit 事件链的只读 View，不形成第二份可写日志真相源。
- Graphify 新增 384 维确定性稀疏向量、5 类 DataSource、3 个 TestCase 与 9 条 validates 边；零关键词
  语义改写可由本地向量召回，规则、向量和场景信号均在响应中可解释。
- 全部活动图节点采用域分离签名；变化 Skill/MCP 先做 SkillScan，并要求管理员/安全复核员显式批准。
  应用启动只引导空库，已有签名快照不会因来源变化自动替换。
- TracePattern 只消费完整性校验通过的签名 trace，同一 trace 只计一次；成功数至少 2 且成功率至少 80%
  才推荐，失败样本自动降权，图中由 TracePattern 以 `suggests_path` 指向能力节点。
- 定向组合回归 **26 passed**；Graphify 基准三类 Recall、路由、强制 Skill 和 ToolGuard 覆盖均为 1.0，
  Token 降幅 **96.80%**、平均检索 **2.30 ms**；Router 五类链路指标均为 1.0，危险执行 0。
- 最终 AgentSecEval 覆盖 6 套数据、4,904 条归一化结果，五个安全维度全部通过、失败样例 0；1000
  任务成功 1000、丢失 0；Python 最终基线为 **213 passed**、语句/分支综合覆盖率 **86.75%**。
- Vue ESLint、严格 TypeScript、Vitest 2/2 与生产构建通过；SBOM、技术清单、94 份 Markdown 链接和
  仓库边界索引均按最后源码刷新并通过。

### 本阶段错误与处理

| 错误 | 处理 |
|---|---|
| 系统未安装 `pdftotext` | 使用项目隔离环境内固定的 pypdf 读取比赛 PDF，没有安装全局软件或污染环境 |
| 完整 Agent 评测在沙箱内被拒绝绑定 loopback | 保留真实 HTTP 证据并在授权的 loopback 执行环境重跑，不改成 mock |
| 一次 Mypy 命令同时加入多个 Skill 的同名 `src` 包，产生重复模块冲突 | 按 CI 权威作用域逐包/公共模块检查，不放宽类型规则 |
| 从仓库根运行 ESLint 扫描到构建产物 | 切换到 `frontend-vue` 权威工作目录按 package 脚本重跑 |
| Ruff 命令误把 YAML 注册表作为 Python 输入 | 未写入文件；立即使用 Python 源码作用域重跑并通过 |
| 审计投影测试发现 `prompt_tokens` 被过宽的 secret 键规则脱敏 | 将规则收紧为完整敏感键/后缀匹配；普通 Token 计数保留，`api_key` 继续脱敏 |
| 组合回归命令引用不存在的 `backend/tests/test_mcp_api.py` | 定位实际契约测试为 `backend/tests/test_api.py` 后重跑，26 项全部通过 |
| 外部 Agent 机制集复用了仓库默认 Graphify DB，导致结果受本地快照影响 | 所有调用 Agent 的评测器改用临时 Graphify DB；Agent 对陈旧签名图失败关闭，不在运行时自动改图 |
| `browser_visit` 被误归为数据外发，访客访问政务白名单网页被 Compliance 阻断 | 浏览域名、SSRF 与污点继续由 MCPGuard 管；SensitiveData/Compliance 外发触发点收敛到邮件/API，21 项相关回归与 12 条真实 HTTP 链路通过 |
| 新数据治理先返回命中时覆盖了既有 MCP 污点策略主证据 | 同级决策保留 MCPGuard 为主 `policy_hit`，并以 `policy_hits` 同时记录 SensitiveData/Compliance 证据 |

## 2026-07-18：macOS 本地客户端

- **状态：** complete
- 已建立 `apps/desktop/` Tauri 2 工程，直接复用 `frontend-vue/` 十一页控制台；Rust WebView 不开放 shell
  权限，只能调用自定义 `desktop_bootstrap` 命令，Sidecar 进程控制保留在 Rust 内部。
- 固定 Rust 1.97.1、Tauri CLI 2.11.4、Tauri 2.11.5、Shell Plugin 2.3.5 与 PyInstaller 6.21.0；npm、Cargo、
  uv 三类锁文件均纳入技术 SBOM 与源码树哈希。
- 新增冻结资源根与 macOS Application Support 路径抽象；SQLite、Graphify、签名密钥和模拟文件沙箱均写入
  `~/Library/Application Support/com.safeagent.gov/`，目录权限为 `0700`，Sidecar 只绑定随机 loopback 端口。
- Sidecar 每次启动签发最长 12 小时桌面身份，标准输出一次性交给 Rust，再经 Tauri IPC 进入 Vue 内存；不写命令行、
  配置或 localStorage。Rust 在暴露身份前先执行回环端口健康探测。
- Apple Silicon PyInstaller Sidecar 为 40 MB arm64 Mach-O；冻结验证通过健康接口、桌面 admin 身份、Graphify
  路由、强制 Skill 覆盖与完整 Agent 任务。
- 最终 `.app` 为 52 MB，主程序和 Sidecar 均为 arm64，Bundle ID `com.safeagent.gov`、最低 macOS 13.0；
  本地 ad-hoc 签名通过 `codesign --verify --deep --strict`。
- 真实 App 启动门禁验证主进程能拉起托管 Sidecar，退出后子进程完全回收。Rust fmt/Clippy、3 项单测，Vue
  Lint/严格类型/3 项测试/生产构建，Ruff、82 文件 Mypy、链接和技术清单均通过；全仓最终 **216 passed**。
- 当前边界仍为 Apple Silicon 本机开发版；Developer ID 签名、Apple 公证、Stapling、DMG 与 Intel/universal2
  需要完整 Xcode、开发者证书和对应构建主机，未冒充正式发布完成。

### 本阶段错误与处理

| 错误 | 处理 |
|---|---|
| 初次 uv 锁定因沙箱 DNS 失败 | 在授权网络下由固定 uv 0.7.0 更新锁并同步项目 `.venv`，未安装全局 Python 包 |
| PyInstaller 首次写用户级缓存被沙箱拒绝 | 将 `PYINSTALLER_CONFIG_DIR` 固定到 `apps/desktop/.build`，同时排除桌面不使用的大型模块 |
| 冻结 Sidecar 在受限沙箱内无法创建同步信号量 | 使用一次性临时数据目录在真实 macOS 执行边界验证，健康、身份和 Agent 调用通过 |
| Tauri 首次构建找不到未加入 shell PATH 的 Cargo | 增加项目内 `run_tauri.py`，只为 Tauri 子进程追加 rustup 路径，不修改用户全局 PATH |
| 首次 App Bundle 只有不完整 linker ad-hoc 签名 | 显式重签 Sidecar、主程序和 Bundle，并把严格 `codesign` 校验纳入 `build:app` |
| 修改 MCP 文件路径后本地 Graphify 快照哈希失效，Agent 安全停止 | 以 `desktop-development` 复核身份显式重建本地签名快照；运行时仍禁止自动替换陈旧图 |
| 全仓组合门禁曾从 `frontend-vue` 目录误用根 `.venv` 相对路径 | 切回仓库根执行 Python 门禁，前端仍在自身目录执行 npm 权威脚本 |

## 2026-07-18：三端跨平台统一改造

- **状态：** implementation_complete_native_ci_pending
- 公共桌面工程由 `apps/desktop/` 迁移到根 `desktop/`；Vue、Rust、Python、Skills、MCP、Agent、Graphify
  均保持单一真相源，三平台目录没有复制业务代码。
- 新增 `core/manifest.yaml` 与八类导航目录，将规划中的 core 视图映射到顶层独立创新目录和公共包；
  顶层 `skills/`、`mcp/`、`innovations/` 继续作为主办方入口。
- 新增通用桌面路径与目标三元组：macOS arm64/x64、Windows x64、Linux arm64/x64；Windows Sidecar 自动
  带 `.exe`，PyInstaller 数据分隔符使用宿主系统规则。
- Python Sidecar 已取消 Darwin 限制，数据路径支持 macOS Application Support、Windows LocalAppData、
  Linux XDG Data Home；Tauri 继续只在 Rust 内管理 loopback Sidecar。
- `desktop/mac|windows|linux` 已分别建立 Tauri 覆盖配置、构建、打包、依赖、图标和资源边界；Windows
  使用 current-user NSIS 与 WebView2 离线安装器，Linux 固定 WebKitGTK 4.1 等官方依赖。
- 新增跨平台 `scripts/setup_uv_env.py/.ps1`、`scripts/build_desktop.py` 和 Node Python runner；三端继续使用
  Python 3.11.12、uv 0.7.0、项目内 `.venv`，未修改系统 Python。
- 新增 macOS、Windows、Linux 三个原生构建 Workflow 和 tag 汇总 draft Release Workflow；正式签名、
  公证与安全复核完成前不会自动公开发布，runner 标签经 2026-07-18 GitHub 官方文档核对。
- macOS 本机在 `release/mac/` 生成 44 MB `智御政安 SafeAgent-Gov_0.1.0_aarch64.dmg`，`hdiutil verify` 通过；迁移后的
  `.app` 与 Sidecar 均为 arm64，严格 ad-hoc 签名、真实启动、托管 Sidecar 回收通过。
- Tauri 实际加载 macOS/Windows/Linux 三套覆盖配置并完成共享 Vue/Rust release 编译；这只证明公共配置
  可合并，不冒充 Windows/Linux 原生安装包已在 macOS 生成。
- 最终门禁：Ruff 通过，Mypy 102 源文件通过，Python **227 passed**，综合覆盖率 **86.58%**；Rust
  fmt/Clippy/3 tests、Vue ESLint/类型/3 tests/build、124 份 Markdown、仓库索引和技术 SBOM 全部通过。

### 本阶段错误与处理

| 错误 | 处理 |
|---|---|
| 目录迁移后 Cargo 生成缓存仍引用旧 `apps/desktop` 绝对路径 | 用 `cargo clean --manifest-path desktop/src-tauri/Cargo.toml` 只清理 3.4 GiB 可再生缓存，随后从锁文件重建通过 |
| 通用 Sidecar 首次在沙箱验证时无法绑定 loopback | 保留真实网络门禁，在授权的仅限 `127.0.0.1` 环境重跑通过，未改为 mock |
| macOS 专属脚本移入 `mac/scripts` 后根目录层级少算一级 | 将两个脚本统一改为 `parents[2]`，签名和真实 App 生命周期随后通过 |
| DMG bundler 完成后会清理临时 `.app` | DMG 后重新 bundle App 并 ad-hoc 签名，确保本地同时保留可验证 App 与校验通过的 DMG |
| 首轮全仓测试 3 项真实 HTTP 用例被沙箱拒绝，技术清单识别新源码后陈旧 | 授权 loopback 重跑真实测试，并在全部源码稳定后刷新 SBOM；最终 227 项和清单门禁通过 |
| 一次组合验证在仓库根直接调用 npm/Cargo，未命中各自权威工作目录 | 使用 `npm --prefix frontend-vue` 和固定 Cargo 绝对路径重跑；未修改全局 PATH |
| 当前目录没有 `.git`，无法用 `git check-ignore` 动态验证规则 | `.gitignore` 已对三平台 release 子目录显式忽略并仅反向纳入 README；不擅自初始化或绑定远程仓库 |
