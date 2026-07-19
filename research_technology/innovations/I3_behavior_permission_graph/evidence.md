# 证据索引

| 类型 | 当前入口 | 状态 |
|---|---|---|
| Skill | `skills/skillscan-gov/` | 标准包已建立 |
| 公共入口 | `skills/skillscan-gov/src/scanner.py` | B3 主路径与 B1 消融均从此导出 |
| AST/图源码 | `skills/skillscan-gov/src/analysis.py`、`advanced_scanner.py` | Python、JS/TS、跨文件数据流和行为—权限图已实现 |
| SBOM/依赖 | `skills/skillscan-gov/src/dependencies.py`、`policies/dependency_risk_snapshot.yaml` | 固定离线版本已实现 |
| 输入加固 | `skills/skillscan-gov/src/package_io.py` | 路径、符号链接、压缩比、加密/嵌套包、数量和大小限制已实现 |
| 策略 | `skills/skillscan-gov/policies/skill_scan_rules.yaml` | 已版本化 |
| 测试 | `skills/skillscan-gov/tests/`、`backend/tests/test_skill_scan.py` | AST 别名、跨文件链、依赖、权限和扫描器自保护已覆盖 |
| 现有评测 | `eval/eval_skill_scan.py` | 小样本冒烟基线 |
| 独立留出数据 | `benchmarks/datasets/skillscan_holdout_v1/` | 50 恶意 + 50 正常，SHA-256 已冻结 |
| B0—B3 运行器 | `benchmarks/runners/eval_skillscan.py` | 已生成逐样例、家族 Recall 和置信区间 |
| 版本化结果 | `benchmarks/results/skillscan_holdout_v1.json` | B3 Recall/Precision 1.0、FPR 0、目标执行 0、P95 约 1.63 ms |
| 五维统一证据 | `benchmarks/results/agentseceval_full_v1.json` | 供应链门禁全部通过，B3 相比关键词 Recall +0.60 |

完整结果必须逐项记录文件、行号、调用链、权限差异和依赖证据。

旧 `backend/core/skill_scan.py` 转发层已按 Stage 8 迁移记录移除，公开入口为 `safeagent_gov.supply_chain`。

该结果来自确定性合成包；B3 Recall 95% Wilson 区间为 `[0.9287, 1.0]`。真实开源插件、构建脚本和纯运行时恶意行为仍需阶段 7 扩展验证。
