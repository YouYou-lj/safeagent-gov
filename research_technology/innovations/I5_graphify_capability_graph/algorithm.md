# 算法

1. 只扫描固定的 `skills/*/manifest.yaml`、`mcp/servers/*/manifest.yaml`、Server Python AST、版本化策略和
   `configs/graphify_registry.yaml`，不导入或执行目标组件。
2. 以规范化标识和 SHA-256 生成 Skill、MCPTool、Policy、TaskIntent、SubAgent、RiskType、ModelProvider、
   PermissionRole、TestCase 与 DataSource 节点。
3. 生成 `requires_skill`、`routes_to_agent`、`can_use_skill`、`can_call_tool`、`guards`、`governed_by`、
   `produces_risk`、`requires_approval` 和 `suitable_for` 边；悬空引用失败关闭。
4. 变化的 Skill/MCP 先做 SkillScan；已有图上的变化必须带复核员身份。事务快照中的每个节点使用
   TraceAudit 密钥做域分离签名，保留审批人与扫描风险。
5. 对意图能力卡和语义样例生成 384 维确定性稀疏向量；将关键词、向量和场景信号融合后，以 NetworkX
   做关系扩展，补齐所有 `mandatory=true` Skill，只返回 Top-K 能力卡片。
6. 只从完整性校验通过且终态明确的 trace 提取执行路径。每个 trace 最多形成一个观察；成功数至少 2 且
   成功率至少 80% 时，签名 TracePattern 才覆盖静态推荐路径，失败观察会自动降权。
7. 健康检查重新扫描来源，检测陈旧快照、无效签名、未批准节点、孤立核心节点、缺失 Schema、未 Guard
   或未绑定策略的工具。已有图不会在进程启动时被自动更新。
