# AgentSecEval-Gov 统一基准

该目录将统一承载版本化数据、运行器、对比基线和逐样例结果。现有 `datasets/`、`eval/`、`reports/eval_results/` 在完成数据清单与兼容迁移前继续作为基线入口，不复制数据。

```text
benchmarks/
├── datasets/   # train/dev/holdout、manifest、许可证、SHA-256
├── runners/    # 统一指标、随机种子、置信区间与场景运行器
├── baselines/  # B0—B3 与消融配置
├── schemas/    # 统一逐样例/汇总结果 Schema
├── failures/   # 只引用失败 ID，不回写冻结 holdout
└── results/    # 版本化逐样例结果和汇总，不手工修改
```

当前可运行命令：

```bash
python research_technology/evaluation/run_all_eval.py
python research_technology/benchmarks/runners/eval_promptshield.py
python research_technology/benchmarks/runners/eval_mcpguard.py
python research_technology/benchmarks/runners/eval_skillscan.py
python research_technology/benchmarks/runners/eval_traceaudit.py
python research_technology/benchmarks/runners/eval_four_scenarios.py
python research_technology/benchmarks/runners/eval_external_agent.py
python research_technology/benchmarks/runners/eval_resilience.py
python research_technology/benchmarks/runners/eval_graphify.py
python research_technology/benchmarks/runners/eval_router.py
python research_technology/benchmarks/runners/eval_model_gateway.py
python research_technology/benchmarks/runners/eval_task_runtime.py
python research_technology/benchmarks/runners/eval_distributed_recovery.py
python research_technology/benchmarks/runners/run_all.py --profile full
```

`run_all.py` 会先复算 I1—I4 的 B0—B3、四场景任务链和独立外部工具型 Agent 的真实 HTTP
进程联调，再验证数据 manifest/SHA-256，最后输出内容安全、数据安全、执行安全、供应链和合规五维结果。
`smoke` 用于每次 CI，`full` 额外运行 1,100 条规模回归、16 并发性能与六类故障注入，并由 CI 每周执行。
当前 full 报告包含 4,904 条归一化逐样例结果；外部 Agent 的 12 条重复集成链路单独列在 `integrations`，
用于验证协议与安全边界，不重复计入独立样本量。

Graphify-Gov 使用独立的 `eval_graphify.py` 复算能力图谱构建、健康、Skill/MCP/Policy Recall@K、路由准确率、
强制安全覆盖、Token 降幅和检索延迟；其 3 条机制样例不并入 4,904 条安全攻击独立统计。

`eval_router.py` 通过 5 条本地忽略的机制案例运行完整 Agent 链，复算子智能体路由召回、意图准确率、
Audit fan-in、强制 Skill/ToolGuard 覆盖、trace 完整性和危险执行数；小样本只证明声明路径闭环。

`eval_model_gateway.py` 在不访问商业云的前提下复算 13 个 Provider 画像与 10 类协议配置覆盖、回退、
身份隔离缓存、受限数据私有路由、零预算阻断、Agent 主链、模型审计和不可信输出标记。协议适配使用注入
传输测试，不冒充 OpenAI、Anthropic、Google、Azure、AWS 或私有模型服务的真实账号联调。

`eval_task_runtime.py` 使用 1000 个注入式无副作用安全任务隔离复算有界队列、32 Worker 并发、终态、强制
覆盖和四事件审计确认；它证明进程内调度基线，不代表 1000 个完整模型 Agent。

`eval_distributed_recovery.py` 使用真实 Compose Redis/Dramatiq 进程，对已认领任务的 security Worker 发送
`SIGKILL`，验证租约过期、替代 Worker 接管、审计完整性和危险执行 0；随后重启 Redis 验证 AOF。该结果
证明单节点进程恢复，不等同于跨节点 Redis 高可用，也不声称 exactly-once。

容器内可复现入口：

```bash
docker compose -f research_technology/reproducibility/docker/docker-compose.yml \
  --profile verification run --rm verification
docker compose -f research_technology/reproducibility/docker/docker-compose.yml \
  --profile verification run --rm verification \
  python research_technology/reproducibility/scripts/container_verify.py --profile full
```

规模集是项目自建的合成压力回归，不作为外部真实分布的泛化结论；现有冻结机制 holdout 与规模集分别呈现，不合并虚增独立样本量。
