# 可证伪假设

在版本化三类政企路由回归集上，Graphify-Gov 应满足：Skill、MCP、Policy Recall@K 均不低于 95%，
Route Accuracy 不低于 90%，强制 Skill 和 ToolGuard 覆盖率均为 100%，相对完整 manifest/SKILL 上下文的
Token Reduction Rate 不低于 70%，平均检索延迟不高于 300 ms。

只要任一门槛未达到，或健康检查发现未受 Guard/Policy 保护的 MCP 工具，该机制即视为失败。三条自建样例
只证明机制闭环，不证明开放世界意图泛化。
