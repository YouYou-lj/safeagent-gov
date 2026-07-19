# 智御政安下一阶段技术执行计划

## 技术目标

把当前规则驱动、模拟闭环的 MVP 升级为具有四条明确创新机制、真实多源输入与 Agent/MCP 链路、独立评测能力和工程复现能力的参赛级技术系统。本文只管理技术研发，不包含报名、报告、视频或提交事务。

## 当前阶段

阶段 0—10 的比赛与主计划技术要求、本地环境治理和最终证据复核均已闭环；后续只做开放数据、真实商业
模型租户和生产基础设施扩展，不把这些外部条件冒充随仓库机制已完成。

## 技术完成定义

- [x] PDF 的四个关键技术方向全部形成“机制设计—独立源码—策略/模型—测试—基准—结果”的闭环。
- [x] 顶层 `skills/`、`mcp/`、`innovations/` 相互独立，并由 `PROJECT_MAP.md` 提供统一评审导航。
- [x] 通用外部工具型 Agent 参考应用独立放置在 `integrations/`，与安全网关和模拟工具执行代码隔离。
- [x] 每个创新点都有明确假设、与基线的差异、消融实验、定量收益、适用边界和失败案例。
- [x] 覆盖用户、网页、文档、RAG、记忆五类输入和文件、Shell、浏览器、API、邮件、数据库六类以上工具动作。
- [x] 危险动作只在隔离沙箱、虚拟文件系统或模拟服务中验证，不在开发主机真实执行。
- [x] 训练/开发/留出数据严格分离；所有指标由固定随机种子和版本化脚本复算。
- [x] 完成单元、契约、集成、端到端、攻击回归、性能和故障注入测试。
- [x] Docker Compose 干净环境可启动全部技术组件并跑完基准测试。

## 阶段 0：仓库边界治理与兼容迁移（第 1 周，优先级 P0）

### 执行任务

- [x] 建立顶层 `PROJECT_MAP.md`，让评审者在 3 分钟内定位四项创新、Skill、MCP、评测和运行入口。
- [x] 将创新 Skill 统一归档到顶层 `skills/`；每个 Skill 使用相同目录契约：`SKILL.md`、`manifest.yaml`、`src/`、`policies/`、`tests/`、`examples/`、`benchmarks/`。
- [x] 建立顶层 `mcp/`，将网关、Server、适配器、策略、Schema、测试和样例从 `agent_demo/` 中解耦。
- [x] 建立顶层 `innovations/`，按 I1—I4 单独说明创新假设、核心算法、代码入口、基线、消融和结果。
- [x] 保留 `backend/`、`frontend/` 作为应用层；应用层只能通过公开接口调用 Skill/MCP，不直接依赖其内部实现。
- [x] 迁移采用兼容层：旧导入路径保留一个迭代，测试全部通过后再移除，禁止复制两份实现。
- [x] 统一包名、模块名、异常类型、日志字段和配置加载方式；消除 `skill.md`/`SKILL.md` 等命名不一致。
- [x] 增加 `pyproject.toml`、锁文件、pre-commit、lint/type/test 配置和 CI 质量门禁。

### 目标结构

```text
safeagent-gov/
├── PROJECT_MAP.md                 # 主办方/评审总入口
├── innovations/                   # 创新点独立展示，不堆放业务代码
│   ├── README.md
│   ├── I1_provenance_risk_graph/
│   ├── I2_taint_capability_guard/
│   ├── I3_behavior_permission_graph/
│   └── I4_verifiable_trace/
├── skills/                        # 可独立加载、测试、评测的安全 Skill
│   ├── README.md
│   ├── promptshield-gov/
│   ├── mcpguard-gov/
│   ├── skillscan-gov/
│   └── traceaudit-gov/
├── mcp/                           # MCP 网关与模拟/沙箱 Server
│   ├── README.md
│   ├── gateway/
│   ├── servers/
│   ├── adapters/
│   ├── policies/
│   ├── schemas/
│   ├── tests/
│   └── examples/
├── backend/                       # API 与应用编排层
├── frontend/                      # Web 控制台
├── agent_demo/                    # Agent 场景与 LangGraph 工作流
├── integrations/                  # 独立外部工具型 Agent 参考应用与进程联调
├── benchmarks/                    # 统一数据、运行器、基线与结果
├── tests/                         # 跨模块契约与 E2E 测试
└── docs/                          # 架构、ADR、威胁模型和接口说明
```

### 验收

- `PROJECT_MAP.md` 中的所有源码、测试和结果链接有效。
- Skill 与 MCP 可分别运行测试，不依赖 Streamlit。
- 应用层通过公开 API/协议调用创新模块，禁止跨目录导入私有符号。
- 迁移前后的 11 项现有测试全部通过，新增目录契约检查通过。

- **状态：** complete

## 阶段 1：威胁模型、技术契约与创新基线（第 1—2 周，P0）

### 执行任务

- [x] 绘制用户、网页、附件、RAG、记忆、Agent、MCP、Skill、审计存储之间的数据流图和攻击树。
- [x] 建立统一 `RiskEvidence`、`PolicyDecision`、`ToolRequest`、`ApprovalState`、`AuditEvent` 数据契约。
- [x] 固化四条创新技术线：
  - I1 来源感知的跨输入攻击证据图与风险融合。
  - I2 能力票据 + 敏感数据污点传播 + 事务型审批。
  - I3 Skill 行为—权限一致性图与供应链评分。
  - I4 带版本和哈希链的可验证审计与任务回放。
- [x] 为每条创新定义可证伪假设、比较基线、主指标、消融开关和失败判据。
- [x] 建立无防护、仅规则、规则+分类器、完整系统四档基线配置。

### 验收

- 四条创新都能回答：新在哪里、解决什么、代码在哪里、如何验证、提升多少、何时失效。
- 所有模块共享公开 Schema，Schema 变更必须通过契约测试。
- **状态：** complete

## 阶段 2：PromptShield-Gov 多源输入安全增强（第 2—3 周，P0）

### 执行任务

- [x] 实现用户、网页、PDF/Word、RAG 结果、历史记忆五类真实适配器与来源元数据。
- [x] 增加规范化、OCR 文本、Unicode/编码混淆、分段与长上下文处理。
- [x] 构建规则层 + 轻量分类器 + 可选 LLM 复核的级联检测，输出各层证据与置信度。
- [x] 以证据图关联跨文档、跨片段、跨轮次攻击，检测分步注入、记忆污染和知识投毒。
- [x] 增加引用可信度、风险聚合、阈值校准、处置策略和低置信度人工复核。
- [x] 建立语义改写、多语言、编码混淆、长上下文与未知模板留出集。

### 指标门槛

- 总体攻击 Recall ≥ 90%，Precision ≥ 90%，正常 FPR ≤ 8%。
- 间接注入 Recall ≥ 88%，知识投毒 Recall ≥ 85%，攻击成功率 ≤ 5%。
- 安全检测 P95 额外延迟 ≤ 1 秒。

### 验收

- 五类输入端到端演示和逐层证据均可查询。
- 有混淆矩阵、95% 置信区间、阈值曲线、失败案例和三层消融结果。
- **状态：** complete

## 阶段 3：MCP-Guard-Gov 工具与任务链控制（第 2—4 周，P0）

### 执行任务

- [x] 将现有工具代码迁移到顶层 `mcp/servers/`，每个 Server 有独立 manifest、Schema、权限和测试。
- [x] 网关统一解析工具名、参数、用户/Agent 身份、任务上下文、输入来源、数据标签和策略版本。
- [x] 实现 RBAC + ABAC + 最小权限能力票据；票据绑定工具、参数范围、数据范围、有效期和单次/多次使用。
- [x] 实现事务型审批状态机：申请、超时、拒绝、脱敏、批准、恢复、撤销、幂等和重放保护。
- [x] 实现敏感数据污点传播，阻断“敏感读取 → 总结/编码 → 浏览器/API/邮件外发”的组合链。
- [x] 增加任务图异常检测，识别步骤重排、工具替换、拆分调用、循环调用和权限升级。
- [x] 覆盖路径穿越、SSRF、私网访问、命令拼接、SQL 写入、TOCTOU、重放和并发审批测试。
- [x] 所有危险工具在容器沙箱或模拟服务中执行；默认网络拒绝、只读根文件系统、CPU/内存/时间限制。

### 指标门槛

- 高风险动作阻断或审批率 ≥ 95%，未授权危险执行数 = 0。
- 审批状态正确率 ≥ 98%，组合攻击成功率 ≤ 3%。
- 网关策略判定 P95 ≤ 200 ms；异常/崩溃时失败关闭率 = 100%。

### 验收

- 文件、Shell、浏览器、API、邮件、数据库动作均有独立 MCP Server 和策略测试。
- 审批后可安全恢复任务，拒绝/超时不能执行，强制 block 不可被人工覆盖。
- **状态：** complete

## 阶段 4：SkillScan-Gov 供应链安全增强（第 3—4 周，P0）

### 执行任务

- [x] 使用 Python AST、JavaScript/TypeScript AST、配置解析替换纯字符串匹配主路径。
- [x] 构建调用图、数据流图和行为—权限图，检测命令执行、恶意下载、隐蔽外联、凭证读取、持久化和动态加载。
- [x] 解析 manifest、requirements、lockfile、package.json，生成 SBOM、许可证和依赖关系。
- [x] 接入版本固定的 CVE、恶意包和拼写劫持数据快照，保证离线可复现。
- [x] 对声明权限与实际行为做一致性评分，输出代码位置、调用链、风险解释和最小权限修复建议。
- [x] 增加混淆、base64/动态 import、反射、运行时下载和跨文件调用检测。
- [x] 加固扫描器自身：ZIP 炸弹、符号链接、目录穿越、超大文件、解析器超时和恶意 AST。

### 指标门槛

- 恶意组件检出率 ≥ 90%，正常组件 FPR ≤ 10%。
- 命令执行、网络外联、敏感文件读取三类 Recall 分别 ≥ 90%。
- 扫描目标代码执行数 = 0；单包扫描超时和资源限制可控。

### 验收

- 至少 50 个恶意和 50 个正常组件的独立留出评测。
- 每个结果可定位到文件、行、调用链、权限差异和依赖证据。
- **状态：** complete

## 阶段 5：TraceAudit-Gov 可验证审计与回放（第 4—5 周，P1）

### 执行任务

- [x] 扩展审计 Schema：来源、策略版本、模型版本、数据集版本、Agent/用户身份、审批角色、工具结果摘要。
- [x] 每个事件记录 `prev_hash`、`event_hash` 和规范化序列化版本，形成 trace 内哈希链。
- [x] 增加 trace 签名/校验、缺失事件检测、顺序篡改检测和导出完整性证明。
- [x] 实现任务回放：固定输入、策略、模型配置和工具模拟响应，复现决策链。
- [x] 建立敏感字段脱敏、最小日志、保留周期和角色化查询策略。

### 指标门槛

- 必填字段完整率 = 100%，内容/顺序/删除篡改检出率 = 100%。
- 任务回放成功率 ≥ 95%，报告与原始事件一致率 = 100%。

### 验收

- 任意 trace 可校验、导出、篡改检测和回放。
- 审计模块故障时高危执行失败关闭，并产生告警事件。
- **状态：** complete

## 阶段 6：AgentSecEval-Gov 独立评测体系（第 4—6 周，P0）

### 执行任务

- [x] 将数据统一放入 `benchmarks/datasets/`，按 train/dev/holdout 分层并生成 manifest、许可证、来源和 SHA-256。
- [x] 数据规模目标：正常输入 ≥300、复杂输入攻击 ≥500、工具越权 ≥200、恶意 Skill ≥50、正常 Skill ≥50、端到端任务链 ≥100。
- [x] 增加内容安全、数据安全、执行安全、供应链、合规五维指标。
- [x] 统一计算 Accuracy、Recall、Precision、FPR、ASR、阻断率、检出率、审计完整率、平均/P95 延迟和 95% 置信区间。
- [x] 实现无防护、规则、级联检测、完整系统的自动基线与消融运行器。
- [x] 建立失败样例回流机制；留出集失败只进入分析集，不反向改写原留出结果。
- [x] CI 运行 smoke benchmark；周度完整 benchmark 检查指标回退。

### 验收

- 一条命令生成版本化逐样例结果、汇总指标、置信区间和对比报告。
- 任一创新点关闭后，系统收益变化可量化，避免无法证明贡献。
- **状态：** complete

## 阶段 7：真实 Agent 集成、四场景验证与工程加固（第 5—7 周，P1）

### 执行任务

- [x] 接入可配置真实 LLM 规划节点，保留无密钥离线回退；二者使用完全相同的安全契约。
- [x] 打通通用外部工具型 Agent：独立 FastAPI 进程经真实 loopback HTTP、Bearer 认证和版本化 planning-only 契约接入；Dify/OpenAI-compatible 保留为可选生产适配器。
- [x] 为政务办公、知识服务、流程办理、运维协同分别构建正常、单点攻击和组合攻击任务链。
- [x] 增加管理员、员工、审批员、审计员角色隔离和身份认证。
- [x] 实现策略版本、灰度、回滚、缓存失效、限流、超时、重试和熔断。
- [x] 完成鉴权、密钥、上传、CORS、日志脱敏、依赖、备份恢复和失败关闭安全自审。
- [x] 测量 CPU、内存、吞吐、平均/P95/P99 延迟和并发稳定性。

### 验收

- 四场景同时通过离线规划器与独立外部 Agent 真实进程联调；错误令牌拒绝、服务中断失败关闭、危险执行为 0。
- Docker Compose 干净环境启动、测试、评测无人工修补。
- 关键服务故障、超时、策略加载失败时无危险默认放行。
- **状态：** complete（不声称官方 Dify/OpenClaw 协议认证或商业租户实测）

## 阶段 8：技术冻结与独立复现（第 8 周，P0）

### 执行任务

- [x] 清除重复实现、失效兼容层、临时数据和未引用策略；保留明确迁移记录。
- [x] 完成全仓 lint、type check、unit、contract、integration、E2E、attack regression、performance 测试。
- [x] 在两套独立干净环境（全新主机 venv + 固定 Python 3.11 验证镜像）复现四场景、完整 benchmark、审计校验和回放。
- [x] 检查所有创新索引链接、代码入口、测试命令、结果路径和版本信息。
- [x] 固定依赖、模型、策略和数据版本，生成 SBOM 与技术版本清单。

### 最终技术门禁

- 单元/契约/集成测试全部通过，关键安全模块分支覆盖率 ≥ 85%。
- 所有 P0 指标达到门槛；任何危险动作真实越权执行数必须为 0。
- 每条创新都能从 `innovations/` 一键定位源码、测试、基线、消融和结果。
- **状态：** complete

## 阶段 9：本地环境隔离与源码许可治理（P0）

### 执行任务

- [x] 固定 Python 3.11.12、uv 0.7.0 与项目内 `.venv`，解释器和缓存均不写入用户全局环境。
- [x] 生成 `uv.lock`，以精确依赖和 `--frozen` 模式统一本地开发与 CI。
- [x] 提供 `scripts/setup_uv_env.sh` 与 `scripts/uv_run.sh`，初始化和运行时均校验版本与锁文件。
- [x] 扩展 `.gitignore`、`.dockerignore`，排除虚拟环境、测试数据、结果、密钥、数据库和本地产物。
- [x] 增加 PolyForm Noncommercial 许可与中文源码开放说明，允许非商业定制，商业使用需书面授权。
- [x] 在固定环境中通过 Ruff、Mypy、仓库契约、技术清单和完整测试。

### 验收

- `.venv` 使用项目内 uv 管理的 Python 3.11.12，`uv pip check` 无依赖破损。
- 完整回归为 156 passed；Ruff、39 个 Mypy 源文件、文档链接与仓库索引均通过。
- **状态：** complete

## 阶段 10：主计划逐项证据复核与剩余增强（持续，P0）

### 执行任务

- [x] 将 `safeagent-gov_plan.md` 的功能、接口、页面、数据、测试和非功能要求映射到当前权威源码与验证命令。
- [x] 实现 Graphify-Gov 基础能力图谱、SQLite/NetworkX 检索、治理健康 API、独立评测与 I5 证据包。
- [x] 实现 SafeRouter 结构化 DAG、风险优先级、有界 fan-out/fan-in、Audit 汇合和失败关闭测试基础。
- [x] 建立统一 Skill Registry/Executor，补齐强制触发、超时、重试、失败策略、审计和执行率指标。
- [x] 将 SafeRouter/Graphify 接入 `/api/agent/run` 的真实分析子智能体主流程并增加路由召回评测。
- [x] 实现统一 Model Gateway、13 个 Provider 画像、10 类协议适配、预算/缓存/回退/成本指标，并接入 Agent 与 Graphify。
- [x] 实现进程内有界队列、三池舱壁、优先级、背压、幂等、SSE 与 1000 任务零丢失门禁。
- [x] 实现 Vue 3/Vite/TypeScript 十一页控制台、真实类型化 API、Pinia/Router、按需构建、容器与 CI 门禁。
- [x] 增加 Redis/Dramatiq 多进程持久队列、宕机恢复与分布式 Worker 部署门禁。
- [x] 补齐 SensitiveData/Compliance 两个独立强制治理 Skill，并在外发、导出和流程动作前触发。
- [x] 补齐服务端身份保护的 `/api/mcp/call` 与五类签名审计只读日志投影。
- [x] 完成 Graphify 本地向量召回、TestCase/DataSource、SkillScan 注册审批、节点签名和可信 TracePattern 学习。
- [x] 复算受影响的测试、评测、SBOM 和技术清单，保持评审入口与实现一致。

- **状态：** complete

## 阶段 11：macOS 本地客户端（Apple Silicon MVP，P0）

### 执行任务

- [x] 读取 `safeagent_gov_client_plans/` 四份平台与系统方案，确认 macOS 采用 Tauri + Vue + FastAPI Sidecar。
- [x] 建立 `apps/desktop/` Tauri 2 工程，复用 `frontend-vue/` 生产界面而不复制安全业务逻辑。
- [x] 新增桌面 Sidecar 入口与 macOS 用户数据目录隔离，固定监听 loopback，并生成桌面专用短期身份。
- [x] 实现 Tauri 对 Sidecar 的启动、健康探测、退出回收和最小权限 Capability/CSP。
- [x] 增加 Apple Silicon Sidecar 构建脚本、开发脚本、`.app` 构建配置和 macOS 使用说明。
- [x] 验证前端、Python Sidecar、Rust/Tauri 单测与开发版 `.app`；记录 ad-hoc 签名、未公证边界。

- **状态：** complete

## 阶段 12：macOS / Windows / Linux 跨平台统一改造（P0）

### 架构原则

- [x] 公共 Python、Vue、Skills、MCP、Agent、Graphify、Eval 只维护一份；三端目录只保存平台构建、签名、安装与运行依赖差异。
- [x] 顶层 `skills/`、`mcp/`、`innovations/` 继续作为主办方评审入口；`core/` 只建立权威实现映射，不复制创新源码。
- [x] 将桌面公共工程从 `apps/desktop/` 迁移到根目录 `desktop/`，并保留明确迁移说明和自动路径门禁。

### 执行任务

- [x] 把 Python Sidecar 数据目录、启动入口、PyInstaller 目标名和验证脚本改为 macOS/Windows/Linux 通用实现。
- [x] 建立 `desktop/mac/`、`desktop/windows/`、`desktop/linux/`，分别提供平台配置、依赖检查、构建和安装包脚本。
- [x] 固定共享 Tauri/Vue/Rust/Python 版本，补齐 macOS app/dmg、Windows MSI/NSIS、Linux AppImage/deb 的配置与产物边界。
- [x] 建立 `scripts/build_desktop.py` 通用入口和 `release/{mac,windows,linux}` 本地产物目录；安装包、签名、公证密钥和测试数据不进入 Git。
- [x] 增加 macOS、Windows、Linux 原生 GitHub Actions，以及 tag 汇总 Release 流水线；每个平台只在对应原生 runner 构建。
- [x] 更新 `PROJECT_MAP.md`、根 README、环境说明、技术 SBOM、仓库索引与跨平台架构说明。
- [x] 增加跨平台路径/目标契约测试，在 macOS 完成 Sidecar、Rust、Vue 和现有 Python 回归；Windows/Linux 原生安装包由对应 CI runner 验证。

### 验收

- 三个平台共用同一个 `desktop/src-tauri/`、`frontend-vue/` 和 Python 核心，不出现平台分叉业务代码。
- macOS 本机开发版继续可构建运行；Windows/Linux 配置和脚本通过静态契约与原生 CI，产物名称和 Release 汇总路径统一。
- 顶层创新目录保持独立清晰，`core/manifest.yaml` 能从规划结构定位到全部权威源码。

- **状态：** complete（代码、macOS 原生产物和三端 CI 配置完成；Windows/Linux 二进制须在仓库推送后由原生 runner 首次产出）

## 依赖关系与并行顺序

```text
仓库治理 ──> 技术契约 ──┬─> PromptShield ──┐
                         ├─> MCP-Guard ─────┼─> Agent 集成 ─> 技术冻结
                         ├─> SkillScan ─────┤
                         └─> TraceAudit ────┘
                                 │
                                 └────────────> AgentSecEval 持续评测
```

## 仓库管理规则

- 分支：`main` 始终可运行；功能使用 `feat/*`，修复 `fix/*`，实验 `exp/*`，重构 `refactor/*`。
- 提交：使用 Conventional Commits；一次提交只处理一个模块边界或一个可验证目标。
- 版本：采用 SemVer；策略、Schema、数据集和模型分别记录独立版本。
- 评审：跨 `skills/`、`mcp/`、公共 Schema 的变更必须经契约测试；关键策略变更需双人复核。
- 目录：模块不能把实现散落在 `examples/`、`docs/` 或页面代码中；共享代码进入明确的公共包。
- 数据：小型样例和 manifest 入库，大型数据/模型使用 DVC 或 Git LFS；结果必须带 commit、配置、随机种子和时间戳。
- 质量：CI 至少运行格式、lint、类型检查、单元/契约测试、安全扫描和 benchmark smoke。
- 依赖：使用锁文件和依赖审计；禁止未固定版本、未说明许可证或用途不明的依赖。
- 证据：创新结果不手工填写，必须由评测脚本生成并链接到具体配置与逐样例结果。

## 已做决策

| 决策 | 理由 |
|---|---|
| 计划只保留技术研发 | 用户明确不需要管理提交材料和赛事行政事项 |
| `skills/`、`mcp/`、`innovations/` 设为顶层独立目录 | 便于主办方快速识别创新资产，并形成清晰包边界 |
| 创新说明与业务代码分离 | `innovations/` 负责证明创新，源码仍在唯一实现目录，避免复制和漂移 |
| 先兼容迁移再移除旧路径 | 保持现有 MVP 可运行，降低一次性重构风险 |
| 当前 100% 指标仅作 smoke baseline | 现有数据规模小且样例与规则同源，不能证明泛化 |

## 错误记录

| 错误 | 尝试次数 | 解决方案 |
|---|---:|---|
| 当前工作目录尚未初始化为 Git 仓库 | 1 | 在阶段 0 纳入 Git 初始化、分支和 CI 规范，不在本轮规划任务中擅自创建远程仓库 |
