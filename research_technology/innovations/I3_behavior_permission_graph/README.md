# I3 Skill 行为—权限一致性图

联合代码行为、调用链、数据流、依赖和 manifest 权限，发现“声明低权限、实际执行高风险行为”的 Skill 供应链威胁。

- 当前实现：安全解包、Python AST、JavaScript/TypeScript 结构化语法树、跨文件调用/数据流、SBOM/CVE 快照、行为—权限差异评分和扫描器自保护。
- 独立证据：50 恶意 + 50 正常冻结包、B0—B3 逐样例结果、路径/符号链接/ZIP 炸弹/深嵌套测试和目标代码零执行证明。
- 适用边界：离线静态分析为主；对纯运行时行为需配合隔离动态分析。

参见 [可证伪假设](hypothesis.md)、[算法](algorithm.md)、[基线](baselines.md) 和 [证据索引](evidence.md)。
