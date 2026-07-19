# PromptShield-Gov 基准入口

_Skill 内只保留评测导航，数据与结果统一归档到顶层 `benchmarks/`。_

---

## 📊 B0—B3 配置

| 配置 | 检测层 | 跨源证据图 |
| --- | --- | --- |
| B0 `disabled` | 无 | 否 |
| B1 `rules` | 单段规则 | 否 |
| B2 `rules_classifier` | 规则 + 轻量分类器 | 否 |
| B3 `full` | 规则 + 分类器 + 可选复核 | 是 |

## 🧪 运行

```bash
python research_technology/benchmarks/runners/eval_promptshield.py
```

数据清单包含 SHA-256、样本族和限制说明。失败样例只进入后续分析集，不回写冻结用例。
