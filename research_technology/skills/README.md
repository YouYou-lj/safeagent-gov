# 安全 Skill 索引

六个强制安全 Skill 均使用统一目录契约：

```text
SKILL.md + manifest.yaml + README.md + src/ + policies/ + tests/ + examples/ + benchmarks/
```

| Skill | 核心能力 | 当前技术状态 |
|---|---|---|
| [promptshield-gov](promptshield-gov/README.md) | 多源输入攻击识别 | 五类来源、级联检测、证据图、B0—B3 与原型留出评测已建立 |
| [mcpguard-gov](mcpguard-gov/README.md) | MCP 裁决、工具链控制 | 票据、污点、事务审批、任务图与 B0—B3 原型留出评测已建立 |
| [skillscan-gov](skillscan-gov/README.md) | Skill/插件供应链分析 | AST、调用/数据流、SBOM/依赖快照、权限图与 100 包 B0—B3 评测已建立 |
| [traceaudit-gov](traceaudit-gov/README.md) | 审计溯源与回放 | 哈希链、HMAC、篡改检测、角色脱敏、签名回放与 80 案例评测已建立 |
| [sensitivedata-gov](sensitivedata-gov/README.md) | 外发/导出敏感数据治理 | 文件化模式、标签传播、无原文证据、脱敏/审批/阻断已建立 |
| [compliance-gov](compliance-gov/README.md) | 政企角色与流程合规 | 外发、导出、流程动作、审批状态和强制审计义务已建立 |

每个 `manifest.yaml` 同时指定唯一入口、最小权限、强制触发阶段、超时、重试、失败策略和必填输入输出。
[统一 Skill Runtime](../paper_sources/docs/skill_runtime.md) 使用显式可信适配器执行六个强制 Skill，manifest 不会触发任意
动态导入。`tests/test_repository_contracts.py` 自动校验结构、入口文件和执行治理字段，禁止恢复小写
`skill.md` 或重复实现。
