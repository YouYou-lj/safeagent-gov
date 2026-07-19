# Stage 7 工程安全自审

| 边界 | 已实现控制 | 失败行为 | 仍需生产接入 |
|---|---|---|---|
| 身份与租户 | 签名 Bearer、角色依赖、服务端身份覆盖、trace/审批租户过滤 | 无令牌 401、错角色 403、跨租户 404 | 接入政企 OIDC/IAM 与密钥轮换 |
| 密钥 | 鉴权、审计、能力票据使用独立密钥；未注入时以 `0600` 文件持久化；镜像忽略运行密钥 | 文件不可读写或格式错误即停止/阻断 | KMS/HSM、轮换和双密钥验证窗口 |
| 输入与上传 | JSON Schema、严格 Planner/工具参数；Skill 上传 10 MB，ZIP 解压 20 MB，临时目录隔离 | 超限 413、未知字段/工具/路径阻断 | 杀毒、内容拆弹、独立动态分析沙箱 |
| 浏览器/API 边界 | 非通配 CORS、Trusted Host、安全响应头、每身份限流 | 配置为空/通配时启动失败，超限 429 | 反向代理 TLS、集中式限流与 WAF |
| 远端规划器 | 显式 HTTPS/loopback endpoint、1 MB 响应上限、超时、瞬态重试、熔断、严格计划 Schema | 显式远端模式停机不执行；`auto` 留痕后离线回退 | 出域 DLP、域名/IP egress allowlist、真实租户验收 |
| 工具执行 | RBAC/ABAC、能力票据、污点、任务图、审批事务、版本绑定 | 策略/账本/审计不可用时不执行 | 对接真实 MCP 前做独立 Server 身份与 mTLS |
| 日志与审计 | 不记录令牌/密钥；敏感值摘要；签名哈希链、租户视图脱敏 | 审计写入失败时危险动作不执行 | WORM/SIEM、告警值班和留存审批 |
| 依赖与容器 | 运行/开发精确锁、CycloneDX SBOM、固定基础镜像摘要、`pip check`、非 root、只读根文件系统、drop ALL、no-new-privileges、资源上限 | 构建、清单陈旧或健康检查失败即停止 | 镜像签名、在线 CVE 门禁、Kubernetes 安全策略 |
| 备份恢复 | SQLite 在线 backup API、前后 integrity check、SHA-256、恢复只写新路径且拒绝覆盖 | 任一检查失败不产出正式备份/恢复库 | 加密备份、异地保留、定期灾备演练 |

默认 Compose 中后端和前端只连接 internal 网络；仅隔离 ingress 同时连接 loopback edge。只有显式叠加
`docker-compose.external.yml` 才给后端增加外联网络，用于配置好的远端 LLM/Dify；该开关不替代生产 egress 防火墙。

已知边界：仓库内所有 MCP Server 仍是无副作用模拟器；通用外部 Agent 已完成独立真实 HTTP 进程联调，
但 OpenAI-compatible/Dify 适配测试仍使用注入传输，没有连接实际第三方租户。现阶段结果证明安全机制与
失败边界可复现，不宣称开放世界泛化或生产级 IAM/恶意软件隔离已经完成。
