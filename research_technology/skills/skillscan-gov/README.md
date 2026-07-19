# SkillScan-Gov package

本目录保存独立 Skill 契约、策略快照、测试和评测导航；唯一扫描实现位于 `src/`，应用层只通过 `safeagent_gov.supply_chain` 调用。

- 公共入口：`src/scanner.py:scan_skill_package`
- B1 token 基线：`src/baseline.py:scan_token_baseline`
- Python/JS/TS 分析：`src/analysis.py`
- SBOM/CVE/恶意包/拼写劫持：`src/dependencies.py`
- ZIP 与输入加固：`src/package_io.py`
- 策略：`policies/skill_scan_rules.yaml`
- 固定依赖快照：`policies/dependency_risk_snapshot.yaml`
- 测试：`tests/`
- 100 包 holdout：`../../benchmarks/datasets/skillscan_holdout_v1/`
- B0—B3 运行器：`../../benchmarks/runners/eval_skillscan.py`
- 结果：`../../benchmarks/results/skillscan_holdout_v1.json`

当前合成原型集 B3 Recall/Precision 为 1.0、正常 FPR 为 0、目标代码执行数为 0。Recall 的 95% Wilson 区间为 `[0.9287, 1.0]`；结果证明机制闭环，但不替代真实生态包验证。
