# TraceAudit-Gov package

本目录保存 I4 的唯一实现、Schema、测试和评测导航；旧 `backend/core/audit_logger.py` 转发层已移除。

- 事件链、角色查询、留存元数据与导出：`src/audit.py`
- 规范化序列化、哈希链、HMAC 签名、旧链迁移：`src/integrity.py`
- 签名回放包与无工具执行回放：`src/replay.py`
- JSON Schema：`policies/audit_schema.json`
- 测试：`tests/`
- 80 案例 holdout：`../../benchmarks/datasets/traceaudit_holdout_v1/`
- B0—B3 运行器：`../../benchmarks/runners/eval_traceaudit.py`
- 版本化结果：`../../benchmarks/results/traceaudit_holdout_v1.json`

B3 在合成原型集上达到字段完整率、六类篡改检出率、回放成功率和报告一致率均为 1.0，回放真实/模拟危险动作执行数为 0。篡改检出率的 95% Wilson 区间为 `[0.9398, 1.0]`，20 个回放的成功率区间为 `[0.8389, 1.0]`。
