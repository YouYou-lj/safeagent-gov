# 证据索引

| 类型 | 当前入口 | 状态 |
|---|---|---|
| Skill | `skills/promptshield-gov/` | 标准包已建立 |
| 基线源码 | `skills/promptshield-gov/src/detector.py` | 已实现唯一源码 |
| 策略/模型 | `skills/promptshield-gov/policies/` | 规则 1.0.0、分类器 0.1.0 |
| 来源与图 | `skills/promptshield-gov/src/sources.py`、`provenance.py` | 第一版已实现 |
| 单元测试 | `skills/promptshield-gov/tests/`、`backend/tests/test_prompt_shield.py` | 来源、分段、级联、跨源与长上下文已覆盖 |
| 冒烟评测 | `eval/eval_prompt_shield.py` | 已接入完整级联 |
| B0—B3 基准 | `benchmarks/runners/eval_promptshield.py` | 34 条合成留出集可复算 |
| 逐样例结果 | `benchmarks/results/promptshield_holdout_v1.json` | 已生成，含 95% CI 与失败样例 |
| 规模与统一证据 | `benchmarks/results/agentseceval_scale_v1.json`、`agentseceval_full_v1.json` | 300 正常 + 500 攻击，B3 Recall/Precision 1.0、FPR/ASR 0 |

结果文件必须记录数据、策略、模型、消融配置和代码版本；本目录不复制源码或结果。

旧 `backend/core/prompt_shield.py` 转发层已按 Stage 8 迁移记录移除，公开入口为 `safeagent_gov.input_security`。

当前 B3 在 34 条机制 holdout 上 Recall/Precision 为 1.0、FPR 为 0；规模回归 300 正常 + 500 攻击同样通过。规模集为实现后自建相关模板，只证明压力回归，不替代外部真实语料泛化。
