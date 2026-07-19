# 技术发现与仓库治理决策

## 用户范围

- 只规划技术完善工作，不管理报名、报告、视频、邮件或提交事务。
- 仓库必须便于主办方查看；创新 Skill、MCP 和创新点说明分别使用顶层独立目录。

## 当前技术基线

- 已有可运行 FastAPI、Streamlit、LangGraph、SQLite MVP。
- PromptShield 已完成五类来源适配、规范化、级联分类与跨来源证据图，并接入统一的远端/离线 Agent 规划契约；通用外部工具型 Agent 已完成独立真实 HTTP 进程联调，商业第三方租户和外部数据泛化仍属扩展项。
- MCP-Guard 已完成类型化上下文、RBAC/ABAC、能力票据、污点传播、事务审批、任务图异常检测、策略灰度回滚、并发/故障压测和六类独立模拟 Server；真实 MCP 服务身份与 mTLS 仍待接入。
- SkillScan 已完成 Python AST、JavaScript/TypeScript 结构化语法树、调用/数据流、行为—权限图、SBOM/CVE 快照和扫描器自保护；纯运行时行为仍需隔离动态分析补充。
- TraceAudit 已完成规范化哈希链、HMAC 签名、内容/顺序/删除/拼接篡改检测、角色脱敏与确定性回放；外部可信时间戳/HSM 属于后续部署增强。
- AgentSecEval 已统一四个机制 holdout 与 1,100 条规模回归；规模数据仍为项目自建相关模板，100% 结果证明机制和规模回归稳定性，不证明外部真实分布泛化。

## 仓库结构问题

| 问题 | 影响 | 治理方式 |
|---|---|---|
| MCP 实现曾藏在 `agent_demo/` | 评审者难判断网关与 Server 是否核心创新 | 已迁移到顶层 `mcp/`，Agent 只保留场景编排与兼容入口 |
| Skill 包命名和结构曾不统一 | 无法独立加载、测试和横向对比 | 已统一 `SKILL.md + manifest + src/policies/tests/examples/benchmarks` |
| 创新点曾无独立索引 | 技术实现存在，但创新主张与证据不易找到 | 已建立 `innovations/I1...I4` 假设、算法、基线、消融与证据包 |
| 评测曾分散在 `datasets/`、`eval/`、`reports/` | 数据版本与结果对应关系不直观 | 已建立 `benchmarks/` 数据目录、统一 Schema、运行器、结果和失败回流分层结构 |
| 应用层曾直接承载安全逻辑 | 模块边界模糊，复用和独立测试困难 | 唯一实现已进入 Skill/MCP，应用通过 `safeagent_gov` 与 `mcp` 公共接口调用 |

## 2026-07-18 跨平台改造决策

- 规划文档的核心要求是“公共能力维护一次、平台差异分目录、原生 runner 分别打包”，不是复制三套应用。
- 现有 `apps/desktop/` 已是可运行的 Tauri 2 公共壳，适合整体迁移为根目录 `desktop/`；Rust 的 `app_data_dir()` 和 Sidecar 管理可直接跨平台复用。
- 当前真正的平台锁定点是 `safeagent_gov/desktop_boot.py` 的 Darwin 拒绝逻辑、macOS 专用数据目录、固定 Apple Silicon PyInstaller 目标名和仅 macOS 的 npm 脚本。
- `frontend/` 已被旧 Streamlit 占用，权威 Vue 控制台位于 `frontend-vue/`。本阶段保留该唯一实现和所有既有容器/CI 契约，避免为目录名重构制造第二份前端。
- 用户此前明确要求创新 Skill、MCP 独立顶层展示，因此不把 `skills/`、`mcp/`、`innovations/` 搬入 `core/`；新增 `core/manifest.yaml` 和分类 README 作为规划视图到权威实现的映射。
- Windows 与 Linux 安装包不能在当前 macOS 主机上伪验证；本机验证公共代码与 macOS 产物，Windows/Linux 由各自 GitHub Actions 原生 runner 构建并校验。
- 2026-07-18 核对官方文档：GitHub 标准 runner 明确提供 arm64 `macos-14`、x64 `windows-2025` 与 x64 `ubuntu-24.04`；Tauri 2 官方 Linux 前置依赖包括 WebKitGTK 4.1、libxdo、AppIndicator、Rsvg 与编译工具，Windows 需要 MSVC C++ Build Tools、WebView2，构建 MSI 还依赖 VBSCRIPT 可选功能。工作流按这些原生边界配置。
| 外部 Agent 证据曾只依赖注入传输 | 无法证明进程、HTTP、认证和中断边界 | 新增顶层 `integrations/reference_agent/`，以独立真实 loopback HTTP 进程纳入统一门禁 |
| 当前目录不是有效 Git 工作树 | 无版本、分支、评审和回滚依据 | 阶段 0 规范初始化 Git、CI、版本和变更规则 |

## 迁移前基线证据

- 2026-07-17 执行现有测试：11 项全部通过，只有 LangGraph/Starlette 上游弃用警告。
- 初始 MCP 调用路径曾为 `agent_demo.langgraph_agent.tools -> backend.core.mcp_guard + agent_demo.mcp_servers.*`；Stage 8 已迁移到 `mcp.adapters.langgraph -> mcp.gateway + mcp.servers`。
- API、评测和测试均直接依赖 `backend.core`，因此迁移必须提供明确兼容层，不能直接删除旧模块。
- `skills/` 中存在系统生成的 `.DS_Store`，应由 `.gitignore` 排除；不作为技术资产。
- 现有 MCP Server 均为安全模拟器，适合直接迁移为独立 Server 包；file server 的虚拟数据根仍需指向 `agent_demo/data`，以保持演示数据兼容。
- `api_call`、`db_query`、`db_write` 已有网关策略但没有独立 Server；阶段 0 可补充“不联网、不连接真实数据库”的模拟实现，使公开工具注册表与策略表一致。

## 四条创新主线

1. **I1 来源感知风险证据图**：融合来源、片段、会话、检索、记忆和指令关系，识别跨源、跨轮次攻击。
2. **I2 污点传播与能力票据**：同时限制 Agent 能做什么、敏感数据能流向哪里，并用事务审批安全恢复。
3. **I3 行为—权限一致性图**：联合 AST、数据流、依赖和 manifest，识别声明与实际行为不一致。
4. **I4 可验证审计链**：记录策略/模型/数据版本和事件哈希，支持篡改检测、定位和回放。

## 阶段 0—1 已验证结论

- Python 可通过 `importlib.import_module` 加载带连字符的标准 Skill 目录，因此源码可保留评审友好的 `promptshield-gov` 命名，同时由 `safeagent_gov` 暴露稳定 Python API。
- 旧 `backend/core` 安全转发与 `agent_demo/mcp_servers` 已在 Stage 8 删除，仓库只保留 `skills/`、`mcp/` 中的唯一实现和 `safeagent_gov` 公共入口。
- Skill manifest、创新证据契约、MCP manifest/注册表/策略一致性和共享 Pydantic Schema 已由自动测试保护。
- 当前 1.0 评测来自随规则一起发布的小样本，只能作为回归冒烟基线；I1 泛化收益必须由未知模板留出集和 B0—B3 对比证明。

## 阶段 2 技术决策

- 网页适配只处理调用方提供的 HTML，不主动联网，避免将内容解析器变成 SSRF 入口；真实抓取必须经 MCP 浏览器网关。
- `content_hash` 基于原文，`normalized_hash` 基于规范化文本；二者同时保留，既能证明原始来源，又能解释检测看到的内容。
- 跨来源拼接只发生在相邻且 `session_id` 相同的来源之间，避免把无关文档偶然拼成攻击短语。
- 来源信任分数只做有限风险增益，不能单独产生高风险结论；真正阻断必须有规则、分类器或跨片段证据。
- 旧规则函数固定为 B1，完整证据图通过新公共入口运行，确保基线与创新机制可以独立消融。
- 轻量分类器使用版本化特征权重和交互项，不宣称为大规模训练模型；它的价值是覆盖规则之外的语义改写并提供可解释中间证据。
- B0—B3 必须区分“检测层消融”和“证据图消融”：B1/B2 独立判断每个来源，只有 B3 允许同会话跨来源关联。
- 34 条原型 holdout 中 B3 相比 B1 Recall 提升 72.73 个百分点，但 95% 区间仍宽；该差值是机制烟测证据，不是最终统计结论。

## 阶段 3 技术决策

- 策略裁决与执行授权分层：`check_tool_call` 可以只做解释性预检，但任何模拟执行都必须经 `guarded_tool_call` 消费能力票据。
- 票据使用 HMAC 签名并绑定主体、租户、任务、工具、精确参数、数据范围、标签、策略版本、有效期和次数；未注入部署密钥时使用数据库目录的 mode-0600 本地密钥，保证审批跨重启可恢复且密钥异常失败关闭。
- 审批不是对 `block` 的人工绕过。只有 `require_approval` 会创建不可变快照；恢复时重新运行当前策略并验证最终参数票据。
- 脱敏批准使用审批保存的完整替代参数，任务图仍校验原计划，能力票据则绑定脱敏后参数，兼顾计划一致性和受控修改。
- 能力票据、审批和任务步骤各自采用原子消费；跨账本无法组成单个分布式事务时优先保证“可能安全地少执行，绝不重复危险执行”。
- 任何摘要、编码或拼接都不能降低数据标签；`/data/approved` 读取结果至少标为 confidential，随后流向未授权浏览器/API/邮件目标时审批或阻断。
- 44 条合成 holdout 中 B3 ASR 为 0，但 95% 区间上界约 9.64%；该结果是机制原型证据，不替代大规模独立攻击集。

## 阶段 4 技术决策

- 原全文 token 扫描作为 B1 独立保留，B3 不再以字符串命中作为 Python/JS/TS 主证据，避免注释和说明文字触发误报。
- Python 使用标准库 AST；JS/TS 在不引入网络依赖的前提下使用项目内 tokenizer 与结构化语法树子集，明确其并非完整编译器，对复杂宏/构建变换需后续 tree-sitter 或隔离构建分析。
- 依赖情报固定为离线版本，任何 CVE/恶意包结论都记录快照版本；不在扫描时访问外部网络，保证复现和避免 SSRF。
- 行为—权限评分把“未声明”和“显式禁止但实际使用”区分展示；过度声明只给最小权限建议，不在没有危险行为时直接判恶意。
- 脱离单文件的调用解析使用 definitions/calls/assignments/sinks 中间事实，再生成 resolves_to 与 cross_file_flows_to 边，便于逐条审计而非只给总分。
- 包输入不使用 `extractall`，逐成员校验并写入临时目录；压缩比、加密成员、嵌套包、特殊文件、符号链接、路径和体积异常均失败关闭。
- 100 包合成 holdout 中 B3 Recall/Precision 为 1.0、FPR 0，但该数据重点验证别名、跨文件、依赖和文本误报机制，不能替代真实插件生态样本。

## 阶段 5 技术决策

- 事件哈希覆盖 trace、sequence、stage、事件、时间、全部版本、actor 和 prev_hash；trace anchor 额外签名事件总数与链头，使尾部删除也可检测。
- 迁移只处理全空 legacy 链；部分哈希缺失不能“补算修复”，否则会把攻击后的状态重新合法化。
- 敏感内容在落库前不可逆摘要；需要回放的原始用户/文档输入保存在受签名身份、角色和租户控制的 trace 上下文，跨租户查询默认返回 404。
- 回放不重新执行任何 MCP Server，只复算 PromptShield 与工具策略，并比较冻结的模拟响应哈希；这样证明裁决可复现而不把回放变成二次副作用入口。
- 策略文件内容、SHA-256、事件链头和 bundle 本身都进入签名包；若 bundle 或策略快照被改动，回放在复算前失败关闭。
- HMAC 的真实性边界是部署密钥；当前明确不宣称跨组织不可抵赖或外部可信时间，后续可用 KMS/HSM/Ed25519/TSA 替换签名后端。

## 阶段 6 技术决策

- 机制 holdout 与规模压力集分别报告：前者证明 B0—B3 机制增益，后者证明规模、性能和工程闭环；禁止把相关模板变体当成 1,100 个独立总体样本来宣称泛化。
- 统一运行器对子模块采用独立 Python 子进程，隔离审计签名密钥、SQLite 状态和 MCP 消费账本，避免运行顺序污染后续结果。
- 数据 manifest 是执行门禁而不是说明文档：实际 SHA-256 或样本数与声明不一致时，全量评测直接失败，不生成“通过”报告。
- 五维汇总采用保守聚合：同一指标有多个证据集时，Recall/保护率取最小值，FPR/ASR/延迟取最大值，不用大规模容易样本稀释小型困难集。
- 统一报告保留所有基线逐样例记录，但失败回流只收集 B3/Full 的失败；B0—B2 的预期失败不污染问题队列。
- CI smoke 复算四条创新的小型 holdout，周度 full 再运行规模集；本地配置成功不等同于远程 CI 已运行，证据中必须区分。
- 规模内容集完全命中属于已知模板覆盖；下一阶段应补充外部真实语料、语义模型或真实 LLM 复核，当前不得将 Wilson 区间解释为真实部署总体区间。

## 阶段 7 技术决策

- 外部模型是“不可信计划提供者”而非执行主体：只允许返回严格 `AgentPlan`，不能接收能力票据/签名密钥/工具输出，也不能直接调用 MCP Server。
- `auto` 与显式远端模式语义不同：前者允许对瞬态故障留痕后回退，后者任何配置、传输或计划错误都停止任务，避免操作者以为使用真实模型时静默变更执行语义。
- 远端只重试网络、超时、429 和 5xx；结构、工具、参数或任务图错误不重试。熔断恢复只允许一个 half-open 探测。
- API 身份只能来自已验签 Bearer；兼容请求体字段可保留展示但不得参与授权。trace/审批/能力票据共同绑定租户和主体。
- 策略灰度采用主体/租户/任务稳定哈希分桶，避免同一任务调用间漂移；审批恢复仍要重新裁决当前版本，旧批准不能穿透新策略。
- Docker Desktop 上 bridge 的 no-masquerade 不能作为可靠的无外联证明；最终拓扑让业务容器只连接 internal 网络，宿主入口由不持有密钥/数据卷的隔离 ingress 提供。
- 容器验收必须实际构建目标 Python 版本。仅在开发机 `pip freeze` 会把解释器特定版本写入锁文件，本次已由 Python 3.11 构建捕获并修正 NumPy 兼容性。
- 通用 `external_agent` 不能用进程内 mock 冒充联调，必须启动独立 HTTP 子进程并验证认证、请求关联、四场景、审计和中断失败关闭；OpenAI-compatible/Dify 仍只声明注入传输，不冒充商业租户实测。

## 技术证明原则

- 每条创新都必须有基线、消融、留出集、逐样例结果和失败分析。
- 测试数据与规则/模型开发数据严格分开。
- 危险操作必须在模拟服务、虚拟文件系统或受限容器中验证。
- `innovations/` 不复制源码，只链接唯一实现，防止双份代码漂移。
- 评审导航必须从根目录开始，3 分钟内可定位四条创新和对应证据。

## 阶段 8 技术决策

- 覆盖率门槛已扩展统计 `backend.core + mcp + external_agent adapter + reference Agent` 的语句与分支综合值；156 项测试实测 89.48%，高于 85% 门槛。
- 运行镜像与验证镜像共享精确运行依赖层，但只有验证目标安装开发锁；源码 COPY 位于工具安装层之后，使证据或源码变化不触发重复下载工具。
- 技术清单不写当前时间，并对锁文件、源码树、策略、数据 manifest 和结果做 SHA-256；外部模型未联调状态也是版本证据的一部分，禁止被 mock 测试覆盖为“已验证”。
- 兼容层在计划约定的一个迭代后删除，并用自动负向门禁防止旧路径回归；迁移记录保留替代入口，不保留双份实现。
- 当前 Python 3.14 全新 venv 与 Python 3.11 固定镜像得到相同的 156 项测试和 89.48% 扩展覆盖率结论；性能值分别报告，不把硬件差异当作结果漂移。

## 阶段 9 环境与许可决策

- 本地开发和 CI 的权威环境固定为 Python 3.11.12、uv 0.7.0 与 `uv.lock`；容器仍使用独立的 Linux 锁文件，但两类环境都限制在 Python 3.11。
- `.venv`、uv 解释器和缓存全部落在仓库已忽略目录；`uv_run.sh` 使用 `--frozen --no-sync`，避免日常命令隐式改锁或访问网络。
- uv 创建的最小环境不要求内置传统 `pip` 模块；依赖一致性使用 `uv pip check`，初始化统一由 `setup_uv_env.sh` 完成。
- 测试数据集、Benchmark 结果、运行数据库、密钥和生成证据默认不提交；小型公开样例与 manifest 需要显式安排后才能纳入版本控制。
- “允许定制、商业需授权”属于 source-available 模式而非 OSI 开源；项目采用 PolyForm Noncommercial 1.0.0，并保留第三方依赖、数据与模型各自许可边界。

## `safeagent-gov_plan.md` 完成度复核（进行中）

- 主计划的终态不仅包含 I1— I4 安全机制，还包含 SafeRouter 多路由子智能体、统一 Skill Registry/Executor、Vue 3 管理控制台、异步并发治理、Model Gateway 和 Graphify-Gov；历史阶段完成记录不能直接证明这些模块完成。
- 主计划要求六类强制安全 Skill，其中当前仓库明确独立展示的核心 Skill 主要是 PromptShield、MCPGuard、SkillScan、TraceAudit；SensitiveData、Compliance、ContextSanitizer/AuditReport 的职责是否作为独立可注册能力存在，尚需从源码和测试核验。
- SafeRouter 已输出结构化子任务、并行组、优先级和超时，并完成有界 fan-out/fan-in；LangGraph 主流程已接入，5 条机制集端到端路由召回为 1.0，外部意图泛化仍待验证。
- 主计划指定的 Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router 已落在独立 `frontend-vue/`；Streamlit 保留为 legacy，不能再作为默认控制面。
- 主计划的高并发目标包括 50—200 QPS、1000 队列任务、审计零丢失、背压/舱壁/优先级队列等；历史 16 并发策略基准不足以证明整条并发架构达标。
- 主计划列出 OpenAI Responses、Anthropic、Gemini、Azure、Bedrock、Vertex、Ollama、vLLM 等协议；当前已知实现只证明 OpenAI-compatible、Dify 和通用 planning-only 参考 Agent，不能据此声称“所有主流协议”已支持。
- `frontend-vue/` 已覆盖计划页面并扩展到十一项治理视图，具有精确 `package-lock.json`、真实 API、路由/身份单测和 lint/type/build 门禁。
- 当前 LangGraph 主流程已加入 Graphify/Router 规划和分析子智能体 DAG；工具执行仍由原有 MCP 能力票据边界最终授权，Router 不直接持有执行权。
- 当前 FastAPI 已有 Agent、Router、Skill Runtime、Graphify、Model Chat、MCP Call、风险、工具审批、审计、评测和策略发布接口；MCP Call 的身份、数据标签、任务图和票据均由服务端生成。
- Graphify 已完成 capability nodes/edges、SQLite/NetworkX、能力卡片、规则/本地向量联合检索、TestCase/DataSource、签名审批快照和可信 TracePattern 学习；开放意图泛化与生产 KMS/HSM 属于外部扩展边界。
- 四个核心 Skill manifest 已补齐 category、execution_mode、trigger_stages、timeout、retries、failure_policy、enabled 和必填输入输出；统一执行器只绑定显式可信适配器。
- NetworkX 3.6.1 与 Vue 工具链已固定并实测；向量库、LiteLLM、Redis/Celery、SQLAlchemy/Alembic 仍未引入，不能把设计选型表视为已验证能力。

## 阶段 10 Skill Runtime 决策

- 四个核心 Skill manifest 已补齐 `category`、`execution_mode`、`trigger_stages`、`timeout_seconds`、`retries`、`failure_policy` 和 `enabled`，Registry 在每次原子加载时严格校验。
- manifest 中的 `entrypoint` 只用于能力说明和完整性核验，不作为任意代码动态导入入口；运行时只调用显式注册的可信核心适配器，第三方或上传包必须先经过 SkillScan 和后续人工注册流程。
- 必选安全 Skill 的超时、异常、审计失败和输出契约错误均失败关闭；重试只面向显式可重试的瞬态异常，不重试参数、权限、策略和安全域错误。
- 统一指标至少覆盖选择/启动/成功次数、必选覆盖率、参数完整率、错误调用率和延迟，并按运行时实例快照输出，避免用静态声明冒充执行证据。
- `/api/skills/metrics` 的强制覆盖率只证明已经提交给 Executor 的声明触发调用；在 Agent Orchestrator 注册阶段级 expected 节点前，不能据此声称端到端不存在绕过 Executor 的遗漏。
- 同步 Python 检查函数超时后，其工作线程不能被强制杀死，因此核心适配器限定为幂等、无外部副作用的检查能力；真正工具副作用始终留在能力票据保护的 MCP 执行边界。
- 意图选择的场景分只增强已有关键词证据，不能让零关键词任务进入专用意图；否则多个场景意图同分时会发生字典序伪路由。
- Agent 对用户输入、文档输入和跨来源融合分别经过 PromptShield Runtime；每次真实工具调用前再次经过 MCPGuard Runtime，后置状态经过 TraceAudit Runtime，并按任务计算强制覆盖率。

## 阶段 10 Model Gateway 决策

- 多模型兼容采用项目内显式协议适配层，不新增 LiteLLM 运行依赖；原因是固定离线环境需要在无网络、无商业凭据时仍可完整测试，且当前协议集合不需要动态 Provider 插件。
- 配置只保存凭据环境变量名，远端画像默认禁用。注入传输的协议契约测试只能证明序列化、解析与治理边界，不能写成供应商兼容认证或真实租户联调。
- 受限数据无条件要求 `private_deployment=true`；缓存键绑定注册表摘要、租户、用户和请求，防止跨租户或跨主体复用模型内容。
- 费用门禁使用服务端上限与请求上限的较小值，显式零预算不能被当成“未设置”；候选按最坏情况 Token 估算筛选，实际使用量继续单独记录。
- 只重试超时、网络、429/5xx 等暂态故障；无效响应不在同一 Provider 重试。审计失败和未知实现异常不降级，直接失败关闭。
- Model Gateway 输出始终是不可信文本。Agent 只接受严格 planning-only JSON，随后再次执行工具白名单、参数 Schema 和 DAG 校验；模型不持有能力票据、MCP handler、签名密钥或工具输出执行通道。
- 默认 Agent 经 Model Gateway 使用确定性离线 Provider，使主链和远端模式共享同一审计、缓存、预算与路由契约；旧 OpenAI-compatible/Dify/外部 Agent 入口保留为显式兼容模式。
- Graphify 从 Model Gateway 注册表生成脱敏模型能力节点，不复制 endpoint 与凭据环境变量名，避免两份模型清单漂移和控制面部署信息泄露。

## 阶段 10 Task Runtime 决策

- 第一阶段先用标准库 `asyncio.PriorityQueue` 建立可测试的单进程基线；该模式继续用于本地单测和 1000 任务隔离压测，Compose 已由后续 Redis/Dramatiq 实现接管。
- security、agent、evaluation 使用独立有界队列和 Worker 数，避免评测或慢 Agent 耗尽安全检测执行槽；Evaluation 单 Worker 还避免现有结果文件并发覆盖。
- critical/high 只在短窗口内等待队列空间，medium/low 立即背压；拒绝任务仍有 `rejected + final_output`，不能无终态消失。
- Handler 只来自显式映射，API payload 经每种任务的严格 Pydantic 模型重验；请求不能选择 Python 入口、伪造身份或动态导入代码。
- 入队审计失败时 handler 不启动，完成审计失败时不返回成功；成功任务固定四个调度事件。幂等键绑定租户和主体，避免跨边界复用。
- 1000 任务基准使用无副作用注入 handler 隔离测量队列/Worker/状态/审计机制，不能外推为 1000 个完整 Agent 或模型请求的吞吐。
- 单进程状态不跨重启恢复，因此只作为本地基线；分布式模式已补 Redis 记录/幂等、Dramatiq ack、任务租约、outbox、死信和真实进程故障恢复。

## 阶段 10 Redis/Dramatiq 分布式任务决策

- Redis ZSET 是等待队列的优先级真相源；Dramatiq 的 actor priority 只影响 Worker 已预取消息，不足以保证全局等待顺序，因此 Broker 消息只作为池级 wake 信号。
- API 的“状态入队”和“通知 Broker”之间用 Redis outbox 解耦；崩溃后可重投，发送后未确认导致的重复 wake 只会认领空队列，不会复制任务记录。
- 任务记录、主体级幂等键、租约、staging、outbox、终态和死信都在同一 Redis 命名空间；WATCH/MULTI 事务负责原子状态转换，不把进程内锁冒充分布式锁。
- Worker 用 15 秒租约和周期心跳。后端对账器既恢复过期租约，也处理“审计确认后、正式入队前”的 staging；没有 Redis 审计确认的 staging 任务失败关闭。
- Dramatiq 框架 `max_retries=0`，应用层只对超时和 `TaskTransientError` 做最多三次有界重试，避免两套重试相乘；永久失败进入应用死信 API。
- 分布式语义明确为 at-least-once。Redis 状态与 SQLite TraceAudit 无法组成单个跨存储事务，因此不声称 exactly-once；handler 必须幂等，真实工具副作用继续依赖一次性能力票据和重放保护。
- 固定 Dramatiq 2.2.0、redis-py 7.4.1、fakeredis 2.36.1；redis-py 暂不跨到 8.x，避免同阶段引入默认协议行为变化。Compose 固定 Redis 8.2.3 多架构摘要。
- Redis 以 UID/GID `999:1000`、只读根、`cap_drop: ALL`、internal-only 且无宿主端口运行；为容器互联关闭 protected-mode。生产部署必须在此基础上增加 TLS/ACL 和跨节点 HA。
- AOF `everysec` 的重启恢复已实测，但它仍有约一秒宿主掉电窗口；本阶段证明单节点进程恢复，不把它宣传为跨可用区容灾。
- Redis 故障期间的协调失败指标属于 best-effort 可观测性，不能反向成为协调器的单点退出条件；双层异常保护和断线存活回归测试现已覆盖这一边界。
- 最终真实门禁强杀 security Worker 后 15.702 秒恢复，2 次投递、1 次恢复、运行时恢复增量 1、终态成功、审计链有效、危险执行 0；随后 Redis 重启仍可读取同一状态。

## 阶段 10 Vue 控制台决策

- Vue 控制台独立位于 `frontend-vue/`，不覆盖旧 Streamlit 文件；默认 Compose 已切换 Vue，Streamlit 只在显式 `legacy-ui` profile 中启动。
- 十一页只通过 FastAPI 公共 API 组合证据，不复制安全算法。MCP 检查页不执行工具，审批页不恢复工具，模型页明确保持 `output_trusted=false` 边界。
- 浏览器 JWT 解码只用于显示；服务端验签、RBAC 和租户隔离仍是授权真相源。localStorage 仅是原型便利，生产必须迁移到 OIDC/BFF 的 HttpOnly Cookie。
- Element Plus 从全量插件注册改为构建期按需导入，最大入口 JS 从约 1,031 kB 降到约 299 kB；路由按页面动态加载。
- Node 24.3.0、全部直接依赖和容器基础镜像均固定版本/摘要；`node_modules`、构建产物、覆盖率和增量状态均不进入版本库或镜像上下文。
- 当前前端证据是静态类型、lint、2 项契约测试和生产构建，不冒充浏览器 E2E、无障碍或真实 OIDC 已验收。

## 阶段 10 最终 Graphify 与评测隔离决策

- Graphify 采用本地 384 维稀疏向量，避免外部 embedding 的网络依赖与任务文本外发；当前小型机制集只证明
  召回链路，不证明开放世界语义泛化。
- Skill/MCP 变更先做 SkillScan 并需复核员显式批准，所有活动节点和 TracePattern 使用域分离签名；进程
  启动只引导空库，陈旧签名图失败关闭，禁止运行时静默重建。
- TracePattern 只接受完整性校验通过的终态 trace，同一 trace 单次消费；至少 2 次成功且成功率达到 80%
  才覆盖静态路径，失败观察自动降低推荐资格。
- 所有会导入 Agent 的评测器必须在导入前设置临时 audit、gateway 与 Graphify 数据库，防止本地历史快照、
  票据或学习路径污染可复算结果。
- `browser_visit` 是受 MCPGuard 域名/SSRF/污点策略约束的读取动作，不等同邮件/API 数据外发；公开政务域
  对访客可读，内部标签进入外部网络仍由 MCPGuard 阻断或审批。

## 关联文件

- 技术执行计划：`plan/task_plan.md`
- 技术要求矩阵：`docs/technical_requirements_matrix.md`
- 仓库规范：`docs/repository_governance.md`
- 评审入口：`PROJECT_MAP.md`

## 阶段 11 macOS 客户端决策

- 四份客户端方案统一指定 Tauri 壳、Vue 3 控制台和 Python FastAPI Sidecar；macOS 首版优先 Apple Silicon，
  产物目标为开发版 `.app`，随后再扩展 `.dmg`、签名与公证。
- 当前主机为 arm64 macOS 26.5.1，Node 24.3.0/npm 11.11.1、Rust 1.97.1 与 Swift Command Line Tools可用；
  完整 Xcode 未选择。Tauri 开发构建可先依赖 Command Line Tools，发布签名/公证需完整 Xcode
  与 Apple Developer 身份。
- 现有 `frontend-vue/` 已有十一页治理控制台，应由桌面构建直接复用，禁止复制第二套页面或安全算法。
- 桌面 Sidecar 必须只监听 `127.0.0.1`，数据写入 macOS Application Support 目录，默认安全模拟模式；
  Shell、真实邮件、删除和数据库写入不得因桌面封装而放宽。
- Redis/Dramatiq、Docker、大型本地模型和外部向量库不进入首版 App；本地 Ollama 只作为可选探测目标。
- Tauri 2 Sidecar 必须在 `bundle.externalBin` 使用相对配置文件的基础名；Apple Silicon 实际文件固定追加
  `-aarch64-apple-darwin`。开发与打包都由同一构建脚本生成该二进制，避免开发壳与发布壳行为漂移。
- Tauri 的 `frontendDist` 会递归嵌入前端产物，因此桌面工程只引用 `frontend-vue/dist`；CSP 只允许自身资源、
  Tauri IPC 与 `127.0.0.1` 回环 API，不加载远程脚本/CDN。
- 桌面身份不写入配置文件或命令行。Sidecar 启动后在标准输出发送一次就绪消息，Rust 保存短期 Bearer，Vue 仅通过
  自定义 Tauri command 取得；浏览器模式仍沿用现有显式登录令牌。
- macOS 运行数据使用 `~/Library/Application Support/com.safeagent.gov/`，源码/内置策略走只读打包资源根；
  SQLite、Graphify、签名密钥和日志走可写用户目录，不能依赖 `.app` 内部路径。
- 桌面 Bearer 只保存在 Pinia 进程内状态，不写 localStorage；App Bundle 使用本地 ad-hoc 签名并通过严格校验，
  该签名只适合本机开发，不替代 Developer ID、公证或 Stapling。
- 技术清单已把桌面 npm lock、Cargo.lock、Rust 目标与 `apps/desktop` 源码纳入 SBOM/源码树哈希；构建产物、
  Sidecar 二进制、`target`、`.build` 与 `node_modules` 均排除在版本库和清单源码范围之外。
