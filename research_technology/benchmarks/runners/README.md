# 运行器契约

运行器统一输出逐样例裁决、耗时、错误类型和汇总指标，固定随机种子，并计算 Recall、Precision、FPR、ASR、阻断率、审计完整率、P95 延迟及 95% 置信区间。

- `eval_promptshield.py`：I1 多源输入 B0—B3。
- `calibrate_promptshield.py`：I1 开发集阈值曲线。
- `eval_mcpguard.py`：I2 策略、污点、票据、审批与任务图 B0—B3。
- `eval_skillscan.py`：I3 token、AST、行为—权限图与依赖情报 B0—B3。
- `eval_traceaudit.py`：I4 版本字段、哈希链、签名篡改检测与确定性回放 B0—B3。
- `eval_agentseceval_scale.py`：1,100 条合成规模回归，危险动作只进入模拟 MCP。
- `run_all.py`：子进程隔离复算、数据哈希验证、结果标准化、五维门禁和失败引用回流。
